"""Display the shared, authoritative SKU forecasting results."""

import streamlit as st

from utils.components import empty_state, guard_protected_page, info_message, render_page_shell
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_data_status, get_forecast_error_message, get_forecast_results


guard_protected_page()
render_page_shell("Demand Forecast", "Analyze · Predictive")
ensure_derived_outputs_for_active_dataset()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export to prepare forecasting inputs.")
    st.stop()

results = get_forecast_results()
if not results:
    empty_state("Forecasting unavailable", "The current processed dataset could not be sent to the approved forecasting pipeline.")
    if get_forecast_error_message():
        info_message(get_forecast_error_message())
    st.stop()

status = results["selection_status"].iloc[0]
st.subheader("SKU-level operational forecast")
st.caption("Approved pipeline: active/current-catalog or client-approved SKUs, dynamic MA window, optimized ES alpha, expanding backtests, MAPE then RMSE selection, and zero-demand observations retained.")
st.dataframe(results["selection_status"], hide_index=True)

forecast = results["forecast_output"]
if forecast.empty:
    info_message("No eligible SKU forecast is available for this upload. Review the eligibility audit below; this commonly occurs for a single monthly file with insufficient historical coverage.")
else:
    st.dataframe(forecast, hide_index=True)
    with st.expander("Bottom-up product and category totals"):
        st.dataframe(results["product_forecast"], hide_index=True)
        st.dataframe(results["category_forecast"], hide_index=True)
    with st.expander("Backtesting metrics and parameter search"):
        st.dataframe(results["validation_metrics"], hide_index=True)
        st.dataframe(results["parameter_search"], hide_index=True)

with st.expander("SKU/category eligibility audit", expanded=forecast.empty):
    st.dataframe(results["eligibility"], hide_index=True)
