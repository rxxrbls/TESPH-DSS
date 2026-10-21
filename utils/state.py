"""Centralized session state for the application foundation."""

from enum import Enum
from typing import Any

import pandas as pd
import streamlit as st


class DataStatus(str, Enum):
    """Lifecycle states for the future ETL-to-analytics workflow."""

    NO_DATA = "NO DATA"
    PROCESSING = "PROCESSING"
    DATA_READY = "DATA READY"


DEFAULT_STATE: dict[str, Any] = {
    "authenticated": False,
    "data_status": DataStatus.NO_DATA.value,
    "selected_upload_name": None,
    "processed_dataset": None,
    "data_contract_version": "0.1",
    "etl_active_step": None,
    "star_schema": None,
    "prepared_transactions": None,
    "active_dataset_id": None,
    "reconciliation_summary": None,
    "etl_validation_report": None,
    "etl_error_message": None,
    "analytics_results": None,
    "analytics_dataset_id": None,
    "analytics_error_message": None,
    "forecast_results": None,
    "forecast_dataset_id": None,
    "forecast_error_message": None,
    # Reserved for approved predictive/risk outputs; the UI does not derive risk levels.
    "risk_results": None,
    "mca_results": None,
    "mca_audit": None,
    "recommendation_results": None,
    "prescriptive_error_message": None,
    "inventory_data": None,
    "inventory_crosswalk": None,
    "inventory_validation": None,
    # A durable, user-facing outcome for the current-stock interaction.  This
    # survives the rerun used to publish the refreshed shared results.
    "stock_upload_feedback": None,
}


def initialize_app_state() -> None:
    """Set predictable defaults once per Streamlit session."""
    for key, value in DEFAULT_STATE.items():
        st.session_state.setdefault(key, value)
    obsolete_criteria = {"Gross Revenue", "Projected Stock-Out Risk", "Stock-Out Frequency"}
    outdated = any(
        frame is not None and obsolete_criteria.intersection(frame.columns)
        for frame in (st.session_state.get(key) for key in
                      ("mca_results", "mca_audit", "recommendation_results"))
    )
    if outdated:
        # A live session may retain scores computed before the approved criteria changed.
        st.session_state["mca_results"] = None
        st.session_state["mca_audit"] = None
        st.session_state["recommendation_results"] = None
        st.session_state["prescriptive_error_message"] = "MCA methodology was updated. Refresh connected stock outputs to replace the previous criteria."
    if st.session_state.get("three_criterion_active"):
        audit = st.session_state.get("mca_audit")
        if audit is not None and "Return Rate" in audit:
            st.session_state["mca_results"] = None
            st.session_state["mca_audit"] = None
            st.session_state["recommendation_results"] = None
            st.session_state["prescriptive_error_message"] = "Refresh stock outputs to replace legacy MCA results."

def restore_runtime_authority() -> None:
    """Load the active runtime snapshot without computing derived outputs.

    Authentication and the protected shell must remain fast. Anything that needs
    analytics or forecasting is resolved lazily in the page that needs it.
    """
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    if st.session_state.get("_runtime_authority_loaded") and st.session_state.get("active_dataset_id") is not None:
        return

    import logging
    _log = logging.getLogger(__name__)

    try:
        from runtime_data_store import load_active_state
        runtime = load_active_state()
        txns = runtime.transactions
        st.session_state["active_dataset_id"] = runtime.dataset_id
        st.session_state["prepared_transactions"] = txns
        st.session_state["processed_dataset"] = txns
        st.session_state["data_status"] = DataStatus.DATA_READY.value if txns is not None and not txns.empty else DataStatus.NO_DATA.value
        st.session_state["_runtime_authority_loaded"] = True
        st.session_state["_bootstrapped"] = True
        from mca_refresh import review_path
        from return_refund_store import load_evidence
        st.session_state["three_criterion_active"] = load_evidence(review_path()) is not None
    except Exception:
        _log.exception("Runtime authority restore failed; app will show an empty state until the user requests data.")
        st.session_state["_runtime_authority_loaded"] = True
        st.session_state["_bootstrapped"] = True


def ensure_derived_outputs_for_active_dataset(
    *, include_analytics: bool = True, include_forecast: bool = True
) -> None:
    """Compute only the missing output families requested by the current page."""
    restore_runtime_authority()
    txns = st.session_state.get("prepared_transactions")
    if txns is None or getattr(txns, "empty", True):
        return

    if include_analytics and not has_valid_analytics_for_active_dataset():
        from analytics_pipeline import run_analytics_pipeline
        set_analytics_results(run_analytics_pipeline(txns))

    if include_forecast and not has_valid_forecast_for_active_dataset():
        try:
            set_forecast_results(run_active_forecasting_pipeline(txns))
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Forecast generation for the active dataset failed; analytics remain available")
            st.session_state["forecast_results"] = None
            st.session_state["forecast_error_message"] = "Forecasting could not be prepared for this dataset."


def run_active_forecasting_pipeline(transactions: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Run the integrated forecast with the governed active-catalog mapping."""
    from active_inventory import build_active_mapping
    from forecasting_pipeline import run_forecasting_pipeline

    mapping, inventory_review = build_active_mapping(transactions)
    results = run_forecasting_pipeline(transactions, mapping=mapping)
    results["inventory_review"] = inventory_review
    return results


def bootstrap_from_active_db() -> None:
    """Compatibility wrapper for explicit data restoration without blocking sign-in."""
    restore_runtime_authority()


def ensure_star_schema_for_active_dataset() -> dict | None:
    """Load Star Schema tables on demand for pages that need dimensions.

    Runtime transactions are restored separately so authentication and the
    dashboard do not pay for a second large database read unless the upload
    page needs its dimension tables.
    """
    restore_runtime_authority()
    if st.session_state.get("data_status") != DataStatus.DATA_READY.value:
        return st.session_state.get("star_schema")

    current = st.session_state.get("star_schema")
    if current is not None:
        return current

    from etl_config import FINAL_OUTPUT_DIR, RUNTIME_DB_PATH

    if RUNTIME_DB_PATH.is_file():
        from star_schema_db import read_runtime_star_schema

        star_schema = read_runtime_star_schema(RUNTIME_DB_PATH)
    else:
        from etl import load_star_schema

        star_schema = load_star_schema(FINAL_OUTPUT_DIR)

    st.session_state["star_schema"] = star_schema
    return star_schema


def reset_application_session() -> None:
    """Remove temporary session data and restore the signed-out defaults."""
    st.session_state.clear()
    st.session_state.update(DEFAULT_STATE)


def get_data_status() -> DataStatus:
    """Return the current application-wide dataset status."""
    return DataStatus(st.session_state["data_status"])


def set_data_status(status: DataStatus) -> None:
    """Future ETL code should call this as its lifecycle changes."""
    st.session_state["data_status"] = status.value


def get_etl_active_step() -> int | None:
    """Return the ETL step currently reported by a future ETL orchestrator."""
    return st.session_state["etl_active_step"]


def set_etl_active_step(step_index: int | None) -> None:
    """Allow the future ETL module to update the shared visual stepper."""
    st.session_state["etl_active_step"] = step_index


def register_selected_upload(file_name: str | None) -> None:
    """Keep the selected filename available to the shell and ETL hook."""
    st.session_state["selected_upload_name"] = file_name


def set_etl_results(
    star_schema: dict | None,
    prepared_transactions: Any | None,
    validation_report: Any | None,
    reconciliation_summary: dict | None = None,
    dataset_id: str | None = None,
    error_message: str | None = None,
) -> None:
    """Store one coherent active runtime snapshot in session state."""
    st.session_state["star_schema"] = star_schema
    st.session_state["prepared_transactions"] = prepared_transactions
    # Keep the original shared-state compatibility field aligned with the
    # canonical handoff; it is not a separate dataset or calculation.
    st.session_state["processed_dataset"] = prepared_transactions
    st.session_state["active_dataset_id"] = dataset_id
    st.session_state["reconciliation_summary"] = reconciliation_summary
    st.session_state["etl_validation_report"] = validation_report
    st.session_state["etl_error_message"] = error_message


def set_etl_failure(validation_report: Any, error_message: str) -> None:
    """Expose a failed staging upload without discarding a valid active snapshot."""
    st.session_state["etl_validation_report"] = validation_report
    st.session_state["etl_error_message"] = error_message


def get_star_schema() -> dict | None:
    """Return the star schema dict or None if unavailable."""
    return st.session_state.get("star_schema")


def get_prepared_transactions() -> Any | None:
    """Return the prepared transactions DataFrame or None."""
    return st.session_state.get("prepared_transactions")


def get_active_dataset_id() -> str | None:
    return st.session_state.get("active_dataset_id")


def get_reconciliation_summary() -> dict | None:
    return st.session_state.get("reconciliation_summary")


def get_etl_validation_report() -> Any | None:
    """Return the ETL validation report or None."""
    return st.session_state.get("etl_validation_report")


def set_analytics_results(results: dict[str, pd.DataFrame] | None, error_message: str | None = None) -> None:
    """Store outputs supplied by the existing descriptive analytics pipeline."""
    st.session_state["analytics_results"] = results
    st.session_state["analytics_dataset_id"] = st.session_state.get("active_dataset_id") if results is not None else None
    st.session_state["analytics_error_message"] = error_message


def get_analytics_results() -> dict[str, pd.DataFrame] | None:
    """Return descriptive analytics generated after the ETL handoff."""
    return st.session_state.get("analytics_results")


def has_valid_analytics_for_active_dataset() -> bool:
    """True only when analytics are both present and tied to the active authority."""
    active_dataset_id = st.session_state.get("active_dataset_id")
    results = st.session_state.get("analytics_results")
    if active_dataset_id is None or results is None or not isinstance(results, dict):
        return False
    if results.get("sales_summary") is None or getattr(results["sales_summary"], "empty", True):
        return False
    return st.session_state.get("analytics_dataset_id") == active_dataset_id


def has_valid_forecast_for_active_dataset() -> bool:
    """True only when forecast output is present and matches the active dataset."""
    active_dataset_id = st.session_state.get("active_dataset_id")
    results = st.session_state.get("forecast_results")
    if active_dataset_id is None or results is None or not isinstance(results, dict):
        return False
    if st.session_state.get("forecast_dataset_id") != active_dataset_id:
        return False

    forecast = results.get("forecast_output")
    if forecast is not None and not getattr(forecast, "empty", True):
        return True

    for candidate_key in ("selection_status", "eligibility"):
        frame = results.get(candidate_key)
        if isinstance(frame, pd.DataFrame) and not getattr(frame, "empty", True):
            return True

    return False


def get_analytics_error_message() -> str | None:
    return st.session_state.get("analytics_error_message")


def set_forecast_results(results: dict[str, pd.DataFrame] | None, error_message: str | None = None) -> None:
    """Store outputs from the authoritative SKU forecasting pipeline."""
    st.session_state["forecast_results"] = results
    st.session_state["forecast_dataset_id"] = st.session_state.get("active_dataset_id") if results is not None else None
    st.session_state["forecast_error_message"] = error_message


def get_forecast_results() -> dict[str, pd.DataFrame] | None:
    return st.session_state.get("forecast_results")


def get_forecast_error_message() -> str | None:
    return st.session_state.get("forecast_error_message")


def set_risk_results(results: pd.DataFrame | None) -> None:
    """Store the current upload's shared stock-risk output."""
    st.session_state["risk_results"] = results


def get_risk_results() -> pd.DataFrame | None:
    return st.session_state.get("risk_results")


def set_prescriptive_results(
    risk: pd.DataFrame | None,
    mca: pd.DataFrame | None,
    recommendations: pd.DataFrame | None,
    error_message: str | None = None,
    *,
    mca_audit: pd.DataFrame | None = None,
) -> None:
    st.session_state["risk_results"] = risk
    st.session_state["mca_results"] = mca
    st.session_state["mca_audit"] = mca_audit
    st.session_state["recommendation_results"] = recommendations
    st.session_state["prescriptive_error_message"] = error_message


def get_mca_results() -> pd.DataFrame | None:
    return st.session_state.get("mca_results")


def get_mca_audit() -> pd.DataFrame | None:
    return st.session_state.get("mca_audit")


def get_recommendation_results() -> pd.DataFrame | None:
    return st.session_state.get("recommendation_results")


def get_prescriptive_error_message() -> str | None:
    return st.session_state.get("prescriptive_error_message")


def set_inventory_results(data: pd.DataFrame, crosswalk: pd.DataFrame, validation: dict) -> None:
    st.session_state["inventory_data"] = data
    st.session_state["inventory_crosswalk"] = crosswalk
    st.session_state["inventory_validation"] = validation


def get_inventory_data() -> pd.DataFrame | None:
    return st.session_state.get("inventory_data")


def get_inventory_crosswalk() -> pd.DataFrame | None:
    return st.session_state.get("inventory_crosswalk")


def get_inventory_validation() -> dict | None:
    return st.session_state.get("inventory_validation")


def set_stock_upload_feedback(
    level: str | None,
    message: str | None = None,
    details: tuple[str, ...] = (),
) -> None:
    """Store a concise, rendered-on-next-run stock workflow outcome."""
    if level is None:
        st.session_state["stock_upload_feedback"] = None
        return
    st.session_state["stock_upload_feedback"] = {
        "level": level,
        "message": message or "",
        "details": tuple(details),
    }


def get_stock_upload_feedback() -> dict[str, Any] | None:
    return st.session_state.get("stock_upload_feedback")


def clear_stock_derived_results() -> None:
    """Invalidate outputs that depend on a stock-to-SKU mapping only."""
    st.session_state["forecast_results"] = None
    st.session_state["forecast_dataset_id"] = None
    st.session_state["forecast_error_message"] = None
    st.session_state["risk_results"] = None
    st.session_state["mca_results"] = None
    st.session_state["mca_audit"] = None
    st.session_state["recommendation_results"] = None
    st.session_state["prescriptive_error_message"] = None
    st.session_state["mca_sensitivity"] = None


def clear_stock_dependent_results() -> None:
    """Invalidate stock-mapped forecasts, risk, MCA, and recommendations."""
    st.session_state["inventory_data"] = None
    st.session_state["inventory_crosswalk"] = None
    st.session_state["inventory_validation"] = None
    st.session_state["stock_upload_feedback"] = None
    clear_stock_derived_results()
