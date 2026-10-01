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
from prescriptive_pipeline import build_sku_mapping_from_stock_upload, run_prescriptive_pipeline
from utils.components import (
    card_header,
    etl_stepper,
    guard_protected_page,
    info_message,
    primary_button,
    persistence_error_state,
    render_page_shell,
    render_upload_summary,
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


def process_stock_upload(file_bytes: bytes, filename: str, stock_as_of, dim_product):
    """Process a stock export using the existing inventory ETL functions."""
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        temp_path = Path(tmp.name)
    try:
        config = InventoryConfig(source_path=temp_path, stock_as_of=stock_as_of)
        inventory = load_current_inventory(config)
        validation = validate_current_inventory(inventory, config)
        return inventory, build_inventory_crosswalk(inventory, dim_product, config), validation
    finally:
        temp_path.unlink(missing_ok=True)


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


def _stock_feedback_details(validation: dict, crosswalk: pd.DataFrame, forecasts: dict, prescriptive: dict) -> tuple[str, ...]:
    """Summarize actual current-stock and downstream output state."""
    checks = validation["row_checks"]
    valid_rows = int(checks["valid"].sum())
    review_rows = int(crosswalk["mapping_review_required"].astype("boolean").fillna(True).sum())
    mapped_rows = int(crosswalk["match_status"].eq("candidate").sum())
    forecast = forecasts.get("forecast_output", pd.DataFrame())
    forecast_skus = int(forecast["SKU"].nunique()) if "SKU" in forecast else 0
    risk_rows = len(prescriptive["risk_results"])
    mca_rows = len(prescriptive["mca_results"])
    recommendation_rows = len(prescriptive["recommendation_results"])
    mca_excluded = max(risk_rows - mca_rows, 0)
    mca_detail = (
        f" MCA excluded {mca_excluded:,} risk SKU(s) because one or more supported criteria were unavailable."
        if mca_excluded
        else ""
    )
    return (
        f"Validated stock rows: {valid_rows:,} of {len(checks):,}.",
        f"Safely mapped stock rows: {mapped_rows:,}; rows requiring mapping review: {review_rows:,}.",
        f"Forecast: {forecast_skus:,} SKU(s); stock-out risk: {risk_rows:,} row(s); "
        f"MCA: {mca_rows:,} row(s); replenishment: {recommendation_rows:,} row(s).{mca_detail}",
    )


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
        st.caption(detail)


def _render_validation_results(report) -> None:
    """Render the complete ETL validation report supplied by the orchestrator."""
    cols = st.columns(4)
    for column, label, value in zip(
        cols,
        ("Rows processed", "Duplicates found", "Missing values", "Type issues"),
        (report.row_count, report.duplicate_count, report.missing_value_count, report.data_type_issues),
        strict=True,
    ):
        with column:
            st.metric(label, f"{value:,}")

    for step in report.step_results:
        st.markdown(f"**{step.step_name}** · {'Passed' if step.success else 'Needs attention'}")
        st.caption(step.message.split("\n\n**Technical detail:")[0])

    if report.warnings:
        with st.expander(f"{len(report.warnings)} validation warning(s)", expanded=False):
            for warning in report.warnings:
                info_message(warning)
    if report.schema_validations:
        with st.expander("Schema validation details", expanded=False):
            for table_name, is_valid in report.schema_validations.items():
                st.markdown(f"- `{table_name}`: {'Valid' if is_valid else 'Schema mismatch'}")


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


guard_protected_page()
render_page_shell("Data Upload & ETL", "Data")

upload_column, schema_column = st.columns((1.2, 1), gap="large")
with upload_column:
    with st.container(border=True):
        card_header("Upload transaction data", "Shopee Seller Centre CSV or XLSX export")
        st.markdown(
            '<div class="upload-zone"><div style="color:#8A8379;font-size:1.45rem">Upload</div>'
            '<p class="upload-zone-title">Drop a Shopee export, or choose a file</p>'
            '<p class="upload-zone-copy">Transaction data is validated before it becomes available to analytics.</p></div>',
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "Choose a CSV or XLSX file",
            type=["csv", "xlsx"],
            label_visibility="collapsed",
            help="Select a Shopee Seller Centre transaction export.",
        )
        register_selected_upload(uploaded_file.name if uploaded_file else None)
        if uploaded_file:
            render_upload_summary(uploaded_file.name)
            if uploaded_file.size > 100 * 1024 * 1024:
                st.warning("This file exceeds 100 MB. Processing is in memory and may take longer than usual.")
            if primary_button("Process dataset", key="process_dataset"):
                had_active_dataset = get_prepared_transactions() is not None
                set_data_status(DataStatus.PROCESSING)
                set_etl_active_step(0)
                progress_area = st.empty()

                def on_step(index: int, _name: str, message: str) -> None:
                    set_etl_active_step(index)
                    with progress_area.container():
                        card_header("ETL pipeline", "Ingest → Clean → Validate → Transform → Load", "Processing")
                        etl_stepper(message)

                result = run_etl_from_upload(uploaded_file.getvalue(), uploaded_file.name, on_step=on_step)
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
                    if not result.reused_existing_outputs or not has_valid_analytics_for_active_dataset():
                        with progress_area.container():
                            card_header("ETL pipeline", "Ingest → Clean → Validate → Transform → Load", "Processing")
                            etl_stepper("Post-ETL / Running descriptive analytics pipeline...")
                        try:
                            set_analytics_results(run_analytics_pipeline(result.prepared_transactions))
                        except Exception:
                            LOGGER.exception("Descriptive analytics failed after a successful ETL handoff")
                            set_analytics_results(None, "Descriptive analytics could not be prepared for this dataset.")
                    if not result.reused_existing_outputs or not has_valid_forecast_for_active_dataset():
                        with progress_area.container():
                            card_header("ETL pipeline", "Ingest → Clean → Validate → Transform → Load", "Processing")
                            etl_stepper("Post-ETL / Running SKU demand forecast pipeline...")
                        try:
                            set_forecast_results(run_forecasting_pipeline(result.prepared_transactions))
                        except Exception:
                            LOGGER.exception("Forecasting failed after a successful ETL handoff")
                            set_forecast_results(None, "Forecasting could not be prepared for this dataset.")
                    set_data_status(DataStatus.DATA_READY)
                else:
                    set_etl_failure(result.validation_report, result.error_message or "Upload could not be processed.")
                    # The active authority is durable and remains available
                    # after a failed upload/reconciliation attempt.
                    set_data_status(DataStatus.DATA_READY if had_active_dataset else DataStatus.NO_DATA)
                st.rerun()
        else:
            st.caption("Accepted formats: CSV and XLSX transaction exports.")

with schema_column:
    with st.container(border=True):
        card_header("Detected schema", "Column mapping")
        schema_placeholder()

with st.container(border=True):
    state_label = "Completed" if get_data_status() is DataStatus.DATA_READY else "Processing" if get_data_status() is DataStatus.PROCESSING else "Not started"
    card_header("ETL pipeline", "Ingest · Clean · Validate · Transform · Load", state_label)
    etl_stepper()

report = get_etl_validation_report()
error_message = st.session_state.get("etl_error_message")
if error_message and report is not None:
    if any(error.startswith("Database persistence failed:") for error in report.errors):
        persistence_error_state()
    else:
        validation_error_state(_validation_issues(report, error_message))

if report is not None:
    with st.container(border=True):
        persistence_failed = any(error.startswith("Database persistence failed:") for error in report.errors)
        report_status = "Validation passed; save failed" if persistence_failed else "All checks passed" if report.is_valid else "Issues found"
        card_header("ETL validation report", "Data-quality assessment", report_status)
        _render_validation_results(report)
        if report.negative_financial_count:
            info_message(
                f"{report.negative_financial_count} negative financial values were preserved unchanged; they may represent refunds, rebates, or fee adjustments."
            )

reconciliation = get_reconciliation_summary()
if reconciliation:
    with st.container(border=True):
        card_header("Active transaction history", "Validated upload reconciliation")
        cols = st.columns(4)
        for column, label, value in zip(
            cols,
            ("Staged rows", "Already in history", "New rows added", "Active rows"),
            (
                reconciliation.get("staged_rows", 0),
                reconciliation.get("existing_exact_rows", 0),
                reconciliation.get("new_rows", 0),
                reconciliation.get("active_rows", 0),
            ),
            strict=True,
        ):
            with column:
                st.metric(label, f"{int(value):,}")
        review_rows = int(reconciliation.get("possible_correction_rows", 0)) + int(
            reconciliation.get("ambiguous_identity_rows", 0)
        )
        if review_rows:
            info_message(
                f"{review_rows:,} changed or ambiguous transaction row(s) were not automatically added; review is required."
            )

star_schema = get_star_schema()
if star_schema:
    success_state(
        "Your transaction data is ready for analysis. Dashboard and Sales & Product Analytics now use this processed dataset.",
        _success_metrics(),
    )
    with st.container(border=True):
        card_header("Star schema datasets", "Cleaned and validated tables")
        for table_name in ("fact_sales", "dim_product", "dim_date", "dim_order", "dim_shipping", "dim_payment"):
            dataframe = star_schema.get(table_name)
            if dataframe is not None:
                with st.expander(f"{table_name} ({len(dataframe):,} rows × {len(dataframe.columns)} columns)"):
                    st.dataframe(dataframe.head(10), use_container_width=True, hide_index=True)
    prepared = get_prepared_transactions()
    if prepared is not None:
        with st.expander("Prepared transactions preview", expanded=False):
            st.dataframe(prepared.head(10), use_container_width=True, hide_index=True)

if get_data_status() is DataStatus.DATA_READY:
    st.divider()
    with st.container(border=True):
        card_header("Stock inventory", "Current inventory snapshot")
        st.caption("Upload a Shopee stock export to validate and crosswalk it against the processed product dimension.")
        _render_stock_feedback()
        stock_file = st.file_uploader("Upload current stock inventory", type=["xlsx"], key="stock_uploader")
        if stock_file:
            st.caption(f"Selected stock file: {stock_file.name}")
            left, right = st.columns(2)
            with left:
                stock_as_of = st.date_input(
                    "Stock snapshot as-of date",
                    value=pd.Timestamp.today().date(),
                    key="stock_as_of",
                )
                stock_date_confirmed = st.checkbox(
                    "I confirm this date matches the uploaded stock snapshot",
                    key=f"confirm_stock_as_of_{stock_file.name}",
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
                if not stock_date_confirmed:
                    st.info("Confirm the date shown for this stock snapshot before validation.")
                elif date_check["valid"] and primary_button("Validate stock data", key="validate_stock"):
                    set_stock_upload_feedback(None)
                    had_active_stock = get_inventory_validation() is not None
                    status = st.status("Validating the selected current-stock snapshot...", expanded=True)
                    try:
                        status.write("Reading the selected workbook and checking stock identifiers and values.")
                        inventory, crosswalk, validation = process_stock_upload(
                            stock_file.getvalue(), stock_file.name, stock_as_of, get_star_schema()["dim_product"]
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
                            status.update(label="Current-stock validation needs attention", state="error", expanded=True)
                            st.rerun()

                        # Publishing a valid snapshot makes every output that
                        # depends on its mapping stale.  Keep the validated
                        # inventory itself if a later stage cannot complete.
                        set_inventory_results(inventory, crosswalk, validation)
                        clear_stock_derived_results()
                        transactions = get_prepared_transactions()
                        if transactions is None:
                            raise ValueError("Active transaction history is unavailable. Process a transaction export before validating current stock.")
                        status.write("Crosswalking current stock to the active consolidated transaction history.")
                        mapping, inventory_audit = build_sku_mapping_from_stock_upload(
                            transactions,
                            crosswalk,
                            stock_as_of=stock_as_of,
                            as_of=pd.Timestamp.today().normalize(),
                        )
                        status.write("Refreshing the SKU forecast using the active consolidated transaction history.")
                        forecasts = run_forecasting_pipeline(transactions, mapping=mapping)
                        forecasts["inventory_review"] = inventory_audit
                        forecasts["sku_mapping"] = mapping
                        set_forecast_results(forecasts)
                        status.write("Refreshing stock-out risk, MCA, and replenishment recommendations.")
                        prescriptive = run_prescriptive_pipeline(
                            transactions,
                            get_analytics_results() or {},
                            forecasts,
                            crosswalk,
                            as_of=pd.Timestamp.today().normalize(),
                        )
                        set_prescriptive_results(
                            prescriptive["risk_results"],
                            prescriptive["mca_results"],
                            prescriptive["recommendation_results"],
                        )
                        set_stock_upload_feedback(
                            "success",
                            "Current-stock snapshot validated and connected outputs refreshed.",
                            _stock_feedback_details(validation, crosswalk, forecasts, prescriptive),
                        )
                        status.update(label="Current-stock validation and connected outputs completed", state="complete", expanded=False)
                        st.rerun()
                    except Exception as exc:
                        LOGGER.exception("Inventory upload failed")
                        # The valid inventory snapshot remains available if a
                        # downstream operation failed, while dependent results
                        # stay cleared rather than presenting stale outputs.
                        clear_stock_derived_results()
                        reason = str(exc) if isinstance(exc, ValueError) and str(exc) else "An unexpected processing error occurred."
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
                        status.update(label="Current-stock processing did not complete", state="error", expanded=True)
                        st.rerun()

    inventory_validation = get_inventory_validation()
    if inventory_validation:
        cols = st.columns(3)
        cols[0].metric("Inventory rows", inventory_validation["row_count"])
        cols[1].metric("Valid rows", int(inventory_validation["row_checks"]["valid"].sum()))
        cols[2].metric("Stock as-of", str(inventory_validation["stock_as_of"] or "Not provided"))
    crosswalk = get_inventory_crosswalk()
    if crosswalk is not None:
        with st.expander(f"Inventory crosswalk ({len(crosswalk):,} rows)", expanded=True):
            st.dataframe(crosswalk.head(20), use_container_width=True, hide_index=True)
elif get_data_status() is DataStatus.NO_DATA and report is None:
    info_message("No data is available yet. Upload and process a Shopee transaction file to begin analysis.")
