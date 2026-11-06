"""Upload Shopee exports and hand in-memory ETL outputs to presentation pages."""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from analytics_pipeline import run_analytics_pipeline
from forecasting_pipeline import run_forecasting_pipeline
from etl_config import InventoryConfig
from etl_inventory import build_inventory_crosswalk, load_current_inventory, validate_current_inventory
from etl_streamlit import run_etl_from_upload
from methodology_config import REPLENISHMENT_CONFIG
from prescriptive_pipeline import build_sku_mapping_from_stock_upload
from mca_refresh import refresh_connected as run_prescriptive_pipeline
from utils.state import (
    clear_stock_dependent_results,
    ensure_star_schema_for_active_dataset,
    run_active_forecasting_pipeline,
)

from utils.components import (
    card_header,
    etl_stepper,
    guard_protected_page,
    info_message,
    primary_button,
    persistence_error_state,
    render_page_shell,
    schema_placeholder,
    success_state,
    validation_error_state,
)
from utils.state import (
    DataStatus,
    clear_stock_derived_results,
    clear_stock_dependent_results,
    get_data_status,
    get_etl_validation_report,
    get_analytics_results,
    get_forecast_results,
    get_active_dim_product,
    has_valid_analytics_for_active_dataset,
    has_valid_forecast_for_active_dataset,
    get_inventory_crosswalk,
    get_inventory_validation,
    get_stock_upload_feedback,
    get_prepared_transactions,
    get_reconciliation_summary,
    get_star_schema,
    register_selected_upload,
    set_analytics_results,
    set_forecast_results,
    set_data_status,
    set_etl_active_step,
    set_etl_failure,
    set_etl_results,
    set_inventory_results,
    set_prescriptive_results,
    set_stock_upload_feedback,
)
from utils.stock_validation import validate_stock_as_of


LOGGER = logging.getLogger(__name__)


def render_return_refund_upload():
    """Explicitly activate the conditionally approved three-criterion workflow."""
    from datetime import date
    import io
    import zipfile
    from three_criterion_mca import Coverage
    with st.expander("Return/refund data — three-criterion MCA", expanded=False):
        st.caption("Upload the cleaned backend CSV or handoff ZIP. Rankings remain provisional until TA weight sign-off. The rate counts recorded refunded quantities, including Refund Only; it is not a physical-return rate.")
        upload = st.file_uploader("Cleaned return/refund evidence", type=["csv", "zip"], key="return_evidence")
        with st.form("return_coverage"):
            a, b = st.columns(2)
            start = a.date_input("Order-date assessment start", date(2020, 5, 22))
            end = b.date_input("Order-date assessment end", date(2026, 4, 24))
            request_start = a.date_input("Request-date coverage start", date(2020, 5, 1))
            request_end = b.date_input("Request-date coverage end", date(2026, 4, 24))
            export_start = a.date_input("Export request dates: first", date(2026, 10, 15))
            export_end = b.date_input("Export request dates: last", date(2026, 10, 16))
            established = st.checkbox("Coverage is confirmed for the selected request dates, including empty monthly files. Later requests are outside this assessment.")
            submitted = st.form_submit_button("Validate and refresh three-criterion MCA")
        if submitted:
            try:
                if upload is None:
                    raise ValueError("Select the cleaned return/refund CSV or ZIP.")
                tx = get_prepared_transactions()
                stock = get_inventory_crosswalk()
                forecasts = get_forecast_results()
                if tx is None or stock is None or not forecasts:
                    raise ValueError("Process sales and connect a valid current-stock snapshot first.")
                if upload.name.lower().endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(upload.getvalue())) as archive:
                        matches = [n for n in archive.namelist() if n.endswith("prepared_return_refund_backend.csv")]
                        if len(matches) != 1:
                            raise ValueError("ZIP must contain exactly one prepared_return_refund_backend.csv.")
                        if archive.getinfo(matches[0]).file_size > 100 * 1024 * 1024:
                            raise ValueError("Return/refund CSV exceeds the 100 MB limit.")
                        data = pd.read_csv(archive.open(matches[0]), dtype=str, keep_default_na=False)
                else:
                    data = pd.read_csv(io.BytesIO(upload.getvalue()), dtype=str, keep_default_na=False)
                coverage = Coverage(*(str(x) for x in (start, end, request_start, request_end, export_start, export_end)),
                                    established=established)
                result = run_prescriptive_pipeline(tx, get_analytics_results() or {}, forecasts, stock,
                    snapshot=data, coverage=coverage, batch_type="return_refund")
                set_prescriptive_results(result["risk_results"], result["mca_results"],
                    result["recommendation_results"], mca_audit=result["mca_audit"])
                st.session_state["mca_sensitivity"] = result["mca_sensitivity"]
                st.session_state["three_criterion_active"] = True
                st.success("Return/refund evidence reviewed. Provisional MCA and connected outputs refreshed.")
            except Exception as exc:
                LOGGER.exception("Return/refund refresh failed")
                st.error(f"Return/refund refresh was not published: {exc}")



def _latest_transaction_date(transactions: pd.DataFrame | None):
    """Return the latest ETL transaction date for the TA-approved stock-date fallback."""
    if transactions is None or transactions.empty or "order_date" not in transactions.columns:
        return None
    dates = pd.to_datetime(transactions["order_date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()



def process_stock_upload(file_bytes: bytes, filename: str, stock_as_of, dim_product, *, stock_definition_confirmed=False):
    """Process a stock export using the existing inventory ETL functions."""
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        temp_path = Path(tmp.name)
    try:
        config = InventoryConfig(
            source_path=temp_path,
            stock_as_of=stock_as_of,
            stock_definition_confirmed=stock_definition_confirmed,
        )
        inventory = load_current_inventory(config)
        validation = validate_current_inventory(inventory, config)
        if not validation.get("valid", False):
            return inventory, build_inventory_crosswalk(inventory, dim_product, config), validation
        crosswalk = build_inventory_crosswalk(inventory, dim_product, config)
        return inventory, crosswalk, validation
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _validation_issues(report, fallback: str | None = None) -> list[str]:
    """Translate structured ETL detail into clear, non-technical user actions."""
    issues = list(report.errors)
    for step in report.step_results:
        if not step.success:
            invalid_values = step.details.get("invalid_values") if step.details else None
            if invalid_values:
                for item in invalid_values[:5]:
                    issues.append(
                        f"Row {item.get('row', '?')}: {item.get('column', 'field')} "
                        f"must be a valid {item.get('expected_type', 'value')}."
                    )
            else:
                issues.append(step.message.split("\n\n**Technical detail:")[0])
    if fallback:
        match = re.search(r"Missing required column:\s*([^\n]+)", fallback)
        if match:
            issues.append(f"Missing required column: {match.group(1)}")
    return list(dict.fromkeys(issue for issue in issues if issue))


def _stock_feedback_details(
    validation_or_crosswalk,
    crosswalk: pd.DataFrame | None = None,
    forecasts: dict | None = None,
    prescriptive: dict | None = None,
) -> tuple[str, ...]:
    """Summarize actual current-stock and downstream output state."""
    if crosswalk is None and isinstance(validation_or_crosswalk, pd.DataFrame):
        crosswalk = validation_or_crosswalk
        validation = None
    else:
        validation = validation_or_crosswalk

    checks = validation.get("row_checks") if isinstance(validation, dict) else None
    valid_rows = int(checks["valid"].sum()) if checks is not None else 0
    review_rows = (
        int(crosswalk["mapping_review_required"].astype("boolean").fillna(True).sum())
        if crosswalk is not None and "mapping_review_required" in crosswalk
        else 0
    )
    mapped_rows = (
        int(crosswalk["match_status"].eq("candidate").sum())
        if crosswalk is not None and "match_status" in crosswalk
        else 0
    )
    forecast = forecasts.get("forecast_output", pd.DataFrame()) if forecasts else pd.DataFrame()
    forecast_skus = int(forecast["SKU"].nunique()) if "SKU" in forecast else 0
    risk_rows = len(prescriptive["risk_results"]) if prescriptive and prescriptive.get("risk_results") is not None else 0
    mca_rows = len(prescriptive["mca_results"]) if prescriptive and prescriptive.get("mca_results") is not None else 0
    recommendation_rows = (
        len(prescriptive["recommendation_results"])
        if prescriptive and prescriptive.get("recommendation_results") is not None
        else 0
    )
    mca_excluded = max(risk_rows - mca_rows, 0)
    mca_detail = (
        f" MCA excluded {mca_excluded:,} risk SKU(s) because one or more supported criteria were unavailable."
        if mca_excluded
        else ""
    )

    details = []
    if checks is not None:
        details.append(f"Validated stock rows: {valid_rows:,} of {len(checks):,}.")
    if crosswalk is not None:
        details.append(f"Safely mapped stock rows: {mapped_rows:,}; rows requiring mapping review: {review_rows:,}.")
    if forecasts is not None and prescriptive is not None:
        details.append(
            f"Forecast: {forecast_skus:,} SKU(s); stock-out risk: {risk_rows:,} row(s); "
            f"MCA: {mca_rows:,} row(s); replenishment: {recommendation_rows:,} row(s).{mca_detail}"
        )
    return tuple(details)


def _render_stock_feedback() -> None:
    """Render the persisted outcome after the stock workflow's publication rerun."""
    feedback = get_stock_upload_feedback()
    if not feedback:
        return
    message = feedback["message"]
    details = feedback.get("details", ())
    if feedback["level"] == "success":
        st.success(message)
    elif feedback["level"] == "warning":
        st.warning(message)
    else:
        st.error(message)
    for detail in details:
        if detail.startswith("**") and "inventory rows need review**" in detail:
            st.warning(detail)
        else:
            st.caption(detail)

def _render_validation_results(report) -> None:
    """Render the complete ETL validation report supplied by the orchestrator."""

    # Summary metrics
    cols = st.columns(4)

    for column, label, value in zip(
        cols,
        ("Rows processed", "Duplicates found", "Missing values", "Type issues"),
        (
            report.row_count,
            report.duplicate_count,
            report.missing_value_count,
            report.data_type_issues,
        ),
        strict=True,
    ):
        with column:
            st.metric(label, f"{value:,}")

    # Validation checks
    st.markdown(
        '<div class="validation-cards-start"></div>',
        unsafe_allow_html=True,
    )

    step_columns = st.columns(len(report.step_results))

    for column, step in zip(
        step_columns,
        report.step_results,
        strict=True,
    ):
        with column:
            status_text = "Passed" if step.success else "Needs attention"

            message = step.message.split(
                "\n\n**Technical detail:"
            )[0]

            card_html = (
                '<div class="validation-card">'
                '<div class="validation-card-header">'
                f'<div class="validation-card-title">{step.step_name}</div>'
                f'<div class="validation-card-status">{status_text}</div>'
                '</div>'
                f'<div class="validation-card-info">{message}</div>'
                '</div>'
            )

            st.markdown(
                card_html,
                unsafe_allow_html=True,
            )

    # Warnings
    if report.warnings:
        with st.expander(
            f"{len(report.warnings)} validation warning(s)",
            expanded=False,
        ):
            for warning in report.warnings:
                info_message(warning)

    # Technical schema details
    if report.schema_validations:
        with st.expander(
            "Schema validation details",
            expanded=False,
        ):
            for table_name, is_valid in report.schema_validations.items():
                st.markdown(
                    f"- `{table_name}`: "
                    f"{'Valid' if is_valid else 'Schema mismatch'}"
                )

def _success_metrics() -> tuple[str, ...]:
    prepared = get_prepared_transactions()
    star_schema = get_star_schema() or {}
    product_count = len(star_schema.get("dim_product", []))
    metrics = [
        f"Processed rows: {len(prepared):,}" if prepared is not None else "Processed rows available",
        f"Products: {product_count:,}",
    ]
    if prepared is not None and "order_date" in prepared.columns:
        dates = pd.to_datetime(prepared["order_date"], errors="coerce").dropna()
        if not dates.empty:
            metrics.append(f"Date range: {dates.min():%d %b %Y} – {dates.max():%d %b %Y}")
    return tuple(metrics)


def _render_etl_pipeline(message: str | None = None) -> None:
    state_label = "Completed" if get_data_status() is DataStatus.DATA_READY else "Processing" if get_data_status() is DataStatus.PROCESSING else "Not started"
    card_header("ETL pipeline", "Prepare and validate transaction data for analysis", state_label)
    etl_stepper(message)


guard_protected_page()
ensure_star_schema_for_active_dataset()
render_page_shell("Data Upload & ETL", "Data")

process_requested = False
upload_bytes: bytes | None = None
upload_name: str | None = None

upload_column, schema_column = st.columns((1.2, 1), gap="small")
with upload_column:
    st.markdown('<span class="upload-schema-row-marker" aria-hidden="true"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<span class="upload-card-marker" aria-hidden="true"></span>', unsafe_allow_html=True)
        card_header(
            "Upload transaction data",
            "Shopee Seller Centre CSV or XLSX export(s)",
            class_name="upload-card-header",
        )
        st.markdown(
            '<div class="upload-zone"><div style="color:#8A8379;font-size:1.45rem">Upload</div>'
            '<p class="upload-zone-title">Drop Shopee export(s), or choose files</p>'
            '<p class="upload-zone-copy">Upload one or multiple monthly files. Validated files are reconciled into active analytics.</p></div>',
            unsafe_allow_html=True,
        )
        uploaded_files = st.file_uploader(
            "Choose CSV or XLSX file(s)",
            type=["csv", "xlsx"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            help="Select one or more Shopee Seller Centre transaction exports. Multiple files will be merged seamlessly.",
        )
        if uploaded_files:
            file_names = [f.name for f in uploaded_files]
            register_selected_upload(", ".join(file_names) if len(file_names) <= 2 else f"{len(file_names)} files selected")
            for f in uploaded_files:
                if f.size > 100 * 1024 * 1024:
                    st.warning(f"'{f.name}' exceeds 100 MB. Processing is in memory and may take longer than usual.")
        else:
            register_selected_upload(None)

        ingestion_mode = st.radio(
            "Upload mode",
            options=["Append to active data", "Replace active dataset"],
            horizontal=True,
            help="Append adds new rows to the current dataset without duplicating; Replace clears prior transactions and loads only the uploaded files.",
        )
        replace_active_mode = ingestion_mode == "Replace active dataset"

        if primary_button("Process dataset", key="process_dataset", disabled=not uploaded_files):
            process_requested = True
            upload_payload = [(f.getvalue(), f.name) for f in uploaded_files]

    with st.expander("Data Management / Reset to Baseline", expanded=False):
        st.caption("Restore the original governed baseline dataset (226,203 transactions). This will clear any uploaded transactions.")
        if st.button("Reset to Baseline Data", key="reset_to_baseline_btn"):
            with st.spinner("Restoring baseline dataset..."):
                from runtime_data_store import reset_active_to_baseline
                rebuilt, prepared, final_id = reset_active_to_baseline()
                clear_stock_dependent_results()
                set_etl_results(rebuilt, prepared, None, dataset_id=final_id)
                set_data_status(DataStatus.DATA_READY)
                st.success("Baseline dataset restored successfully (226,203 transactions).")
                st.rerun()

with schema_column:
    with st.container(border=True):
        card_header("Detected schema", "Standard Shopee format")
        prepared_tx = get_prepared_transactions()
        star = get_star_schema()
        if prepared_tx is not None and star:
            st.success("Standard Shopee Schema Verified (37 fields)")
            st.caption(
                f"Active Star Schema: fact_sales ({len(star.get('fact_sales', [])):,} rows), "
                f"dim_product ({len(star.get('dim_product', [])):,} products), "
                f"dim_date, dim_order, dim_shipping, dim_payment."
            )
        else:
            st.info("Schema will be verified automatically upon dataset processing.")
        with st.expander("Detected schema field dictionary", expanded=False):
            schema_placeholder(prepared_tx, star)

etl_pipeline_slot = st.empty()
with etl_pipeline_slot.container():
    with st.container(border=True):
        _render_etl_pipeline()

if process_requested and upload_payload:
    had_active_dataset = get_prepared_transactions() is not None
    set_data_status(DataStatus.PROCESSING)
    set_etl_active_step(0)

    def update_etl_progress(message: str | None = None) -> None:
        with etl_pipeline_slot.container():
            with st.container(border=True):
                _render_etl_pipeline(message)

    update_etl_progress("Starting ETL pipeline...")

    def on_step(index: int, _name: str, message: str) -> None:
        set_etl_active_step(index)
        update_etl_progress(message)

    result = run_etl_from_upload(
        upload_payload,
        on_step=on_step,
        replace_active=replace_active_mode,
    )
    if result.success:
        # A new active runtime snapshot invalidates prior stock,
        # forecast, risk, MCA, and recommendation outputs. Do this
        # only after a successful reconciliation so a failed
        # staging upload cannot discard valid session data. When the
        # business authority is unchanged, reuse the existing runtime
        # outputs instead of rerunning the whole downstream pipeline.
        if not result.reused_existing_outputs:
            clear_stock_dependent_results()
        set_etl_results(
            result.star_schema,
            result.prepared_transactions,
            result.validation_report,
            reconciliation_summary=result.reconciliation_summary,
            dataset_id=result.dataset_id,
        )
        set_etl_active_step(4)
        if not result.reused_existing_outputs or not has_valid_analytics_for_active_dataset():
            update_etl_progress("Post-ETL / Running descriptive analytics pipeline...")
            try:
                set_analytics_results(run_analytics_pipeline(result.prepared_transactions))
            except Exception:
                LOGGER.exception("Descriptive analytics failed after a successful ETL handoff")
                set_analytics_results(None, "Descriptive analytics could not be prepared for this dataset.")
        if not result.reused_existing_outputs or not has_valid_forecast_for_active_dataset():
            update_etl_progress("Post-ETL / Running SKU demand forecast pipeline...")
            try:
                set_forecast_results(run_active_forecasting_pipeline(result.prepared_transactions))
            except Exception:
                LOGGER.exception("Forecasting failed after a successful ETL handoff")
                set_forecast_results(None, "Forecasting could not be prepared for this dataset.")
        set_data_status(DataStatus.DATA_READY)
        update_etl_progress()
    else:
        set_etl_failure(result.validation_report, result.error_message or "Upload could not be processed.")
        # The active authority is durable and remains available
        # after a failed upload/reconciliation attempt.
        set_data_status(DataStatus.DATA_READY if had_active_dataset else DataStatus.NO_DATA)
        update_etl_progress(result.error_message or "Upload could not be processed.")
    st.rerun()

report = get_etl_validation_report()
error_message = st.session_state.get("etl_error_message")
if error_message and report is not None:
    db_persistence_errors = [error for error in report.errors if error.startswith("Database persistence failed:")]
    if db_persistence_errors:
        persistence_error_state(detail=db_persistence_errors[0])
    else:
        validation_error_state(_validation_issues(report, error_message))

star_schema = get_star_schema()
if star_schema:
    success_state(
        "Your transaction data is ready for analysis and is now available to the system's analytical modules.",
        _success_metrics(),
    )
    col_nav, _ = st.columns([1.6, 2])
    with col_nav:
        if st.button("Proceed to Dashboard & Analytics →", type="primary", use_container_width=True, key="proceed_to_dashboard"):
            st.switch_page("pages/dashboard.py")

if get_data_status() is DataStatus.DATA_READY:
    st.divider()
    with st.container(border=True):
        card_header("Stock inventory", "Current inventory snapshot")

        inventory_validation = get_inventory_validation()

        if inventory_validation:
            cols = st.columns(3)
            cols[0].metric("Inventory rows", inventory_validation["row_count"])
            cols[1].metric("Valid rows", int(inventory_validation["row_checks"]["valid"].sum()))
            cols[2].metric("Stock as-of", str(inventory_validation["stock_as_of"] or "Not provided"))

        st.markdown(
            '<div class="upload-zone">'
            '<div style="color:#8A8379;font-size:1.45rem">Upload</div>'
            '<p class="upload-zone-title">Drop a Shopee stock export, or choose a file</p>'
            '<p class="upload-zone-copy">Upload a Shopee stock export to validate and crosswalk it against the processed product dimension.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div style='height: 1rem;'></div>",
            unsafe_allow_html=True,
        )
        _render_stock_feedback()

        stock_file = st.file_uploader(
            "Upload current stock inventory",
            type=["xlsx"],
            key="stock_uploader",
            label_visibility="collapsed",
        )
        if stock_file:
            st.caption(f"Selected stock file: {stock_file.name}")
            left, right = st.columns(2)
            latest_transaction_date = _latest_transaction_date(get_prepared_transactions())
            stock_date_default = latest_transaction_date or pd.Timestamp.today().date()
            with left:
                if latest_transaction_date is not None:
                    st.caption(
                        "If this stock file has no snapshot date, the date below defaults "
                        "to the latest transaction date as the TA-approved estimate. "
                        "Replace it with the actual snapshot date when known."
                    )
                else:
                    st.caption(
                        "No transaction date is available for an estimate. Enter and confirm the "
                        "actual stock snapshot date; today's date is only an input prompt."
                    )
                stock_as_of = st.date_input(
                    "Stock snapshot as-of date",
                    value=stock_date_default,
                    key="stock_as_of",
                )
                stock_date_confirmed = st.checkbox(
                    "I confirm this date, including the latest-transaction-date fallback if needed",
                    key=f"confirm_stock_as_of_{stock_file.name}",
                )
                stock_definition_confirmed = st.checkbox(
                    "I confirm Stock is net sellable quantity (on-hand minus reserved/allocated)",
                    key=f"confirm_stock_definition_{stock_file.name}",
                )
            with right:
                threshold_days = st.number_input(
                    "Recency warning threshold (days)",
                    min_value=1,
                    value=REPLENISHMENT_CONFIG.max_stock_age_days,
                )
            if stock_as_of:
                date_check = validate_stock_as_of(stock_as_of, threshold_days=threshold_days)
                for issue in date_check["issues"]:
                    (st.warning if date_check["is_stale"] else st.error)(issue)

                if stock_date_confirmed and date_check["is_stale"]:
                    st.caption(
                        "A stale snapshot can pass file validation, but stock rows older "
                        "than the configured freshness limit are excluded from connected "
                        "risk and replenishment calculations. The warning threshold above "
                        "does not change that limit."
                    )
                if not stock_definition_confirmed:
                    st.info("Confirm the stock meaning before using these values for risk or replenishment.")
                validate_stock_clicked = False
                if date_check["valid"]:
                    validate_stock_clicked = st.button(
                        "Validate stock data",
                        key="validate_stock",
                        disabled=not (stock_date_confirmed and stock_definition_confirmed),
                        type="primary",
                        width="stretch",
                    )

                if validate_stock_clicked:
                    set_stock_upload_feedback(None)
                    had_active_stock = get_inventory_validation() is not None
                    with st.spinner("Processing current-stock data..."):
                        try:
                            dim_product = get_active_dim_product()
                            inventory, crosswalk, validation = process_stock_upload(
                                stock_file.getvalue(), stock_file.name, stock_as_of, dim_product,
                                stock_definition_confirmed=stock_definition_confirmed,
                            )
                            valid_rows = int(validation["row_checks"]["valid"].sum())
                            if not validation["valid"]:
                                invalid_rows = len(validation["row_checks"]) - valid_rows
                                retained_snapshot = " The previously validated stock snapshot remains active." if had_active_stock else ""
                                set_stock_upload_feedback(
                                    "error",
                                    "Current-stock validation failed. Correct the invalid rows and validate the same snapshot again." + retained_snapshot,
                                    (f"Valid rows: {valid_rows:,} of {len(validation['row_checks']):,}; invalid rows: {invalid_rows:,}.",),
                                )
                                st.rerun()

                            # Publishing a valid snapshot makes every output that
                            # depends on its mapping stale. Keep the validated
                            # inventory itself if a later stage cannot complete.
                            set_inventory_results(inventory, crosswalk, validation)
                            clear_stock_derived_results()
                            transactions = get_prepared_transactions()
                            if transactions is None:
                                raise ValueError("Active transaction history is unavailable. Process a transaction export before validating current stock.")
                            mapping, inventory_audit = build_sku_mapping_from_stock_upload(
                                transactions,
                                crosswalk,
                                stock_as_of=stock_as_of,
                                as_of=pd.Timestamp.today().normalize(),
                                max_stock_age_days=int(threshold_days),
                            )
                            forecasts = run_forecasting_pipeline(transactions, mapping=mapping)
                            forecasts["inventory_review"] = inventory_audit
                            forecasts["sku_mapping"] = mapping
                            set_forecast_results(forecasts)
                            prescriptive = run_prescriptive_pipeline(
                                transactions,
                                get_analytics_results() or {},
                                forecasts,
                                crosswalk,
                                as_of=pd.Timestamp.today().normalize(),
                                max_stock_age_days=int(threshold_days),
                            )
                            set_prescriptive_results(
                                prescriptive["risk_results"],
                                prescriptive["mca_results"],
                                prescriptive["recommendation_results"],
                                mca_audit=prescriptive.get("mca_audit"),
                            )
                            st.session_state["mca_sensitivity"] = prescriptive.get("mca_sensitivity")
                            set_stock_upload_feedback(
                                "success",
                                "Current-stock snapshot validated and connected outputs refreshed.",
                                _stock_feedback_details(validation, crosswalk, forecasts, prescriptive),
                            )
                            st.rerun()
                        except Exception as exc:
                            LOGGER.exception("Inventory upload failed")
                            # The valid inventory snapshot remains available if a
                            # downstream operation failed, while dependent results
                            # stay cleared rather than presenting stale outputs.
                            clear_stock_derived_results()
                            reason = (
                                f"{type(exc).__name__}: {exc}"
                                if str(exc).strip()
                                else f"{type(exc).__name__} (no error detail was provided)"
                            )
                            set_prescriptive_results(
                                None,
                                None,
                                None,
                                "Current stock was not connected to all downstream outputs. " + reason,
                            )
                            set_stock_upload_feedback(
                                "error",
                                "Current-stock processing did not complete. The validated snapshot is retained, but forecast, risk, MCA, and replenishment outputs were not refreshed.",
                                (f"Reason: {reason}",),
                            )
                            st.rerun()

elif get_data_status() is DataStatus.NO_DATA and report is None:
    info_message("No data is available yet. Upload and process a Shopee transaction file to begin analysis.")

render_return_refund_upload()
