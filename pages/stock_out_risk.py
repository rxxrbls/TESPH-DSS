"""Stock-out risk dashboard."""

import streamlit as st

from utils.analytics_display import render_risk_summary as render_shared_risk_summary
from utils.components import (
    empty_state,
    guard_protected_page,
    info_message,
    render_page_shell,
)
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_data_status, get_prescriptive_error_message, get_forecast_results, get_inventory_crosswalk, get_risk_results


guard_protected_page()

ensure_derived_outputs_for_active_dataset()

render_page_shell(
    "Stock-Out Risk",
    "Analyze · Predictive",
)


if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing stock-out risk inputs.")
    st.stop()

forecast_results = get_forecast_results()
forecast = forecast_results.get("forecast_output") if forecast_results else None
crosswalk = get_inventory_crosswalk()
risk_output = get_risk_results()
st.subheader("Connected inputs")
if forecast is None or forecast.empty:
    info_message("No eligible SKU forecast is available for this dataset, so stock-out risk is not calculated. The Forecast page shows the eligibility/insufficient-history reason.")
elif crosswalk is None:
    info_message("Forecast demand is ready. Upload and validate the current-stock export on Data Upload to connect Current Stock before calculating stock-out risk.")
    st.dataframe(forecast, hide_index=True)
else:
    stock_columns = [column for column in ("product_key", "candidate_product_keys", "SKU", "Stock", "stock_as_of", "match_status", "mapping_review_required", "stock_definition_status", "review_reasons") if column in crosswalk.columns]
    st.dataframe(crosswalk[stock_columns], hide_index=True)
    if risk_output is not None and not risk_output.empty:
        info_message("Stock-out risk is available for the safely matched current-stock rows. Rows flagged for mapping review are excluded from the connected calculation.")
    else:
        info_message("Forecast demand and current-stock rows are available, but stock-out risk has not been calculated for safely matched rows yet.")

if risk_output is not None and not risk_output.empty:
    st.subheader("SKU stock-out risk")
    render_shared_risk_summary(risk_output)
    st.dataframe(risk_output, hide_index=True)
else:
    error_message = get_prescriptive_error_message()
    if error_message:
        info_message(error_message)
    else:
        info_message("Upload and validate a current-stock snapshot to calculate DOI and forecast-horizon risk for safely matched SKUs.")
