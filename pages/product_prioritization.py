"""MCA product-priority page using shared application state."""

import streamlit as st

from utils.components import empty_state, guard_protected_page, info_message, render_page_shell
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_results, get_data_status, get_forecast_error_message, get_forecast_results, get_mca_results, get_prescriptive_error_message


guard_protected_page()
render_page_shell("Product Prioritization", "Decide · Prescriptive")
ensure_derived_outputs_for_active_dataset()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing product priority.")
    st.stop()

analytics = get_analytics_results() or {}
forecast_results = get_forecast_results() or {}
forecast = forecast_results.get("forecast_output")
if forecast is None or forecast.empty:
    info_message("Forecasted demand is not available for MCA because this dataset has no eligible SKU forecast. See the Forecast eligibility audit.")
    if get_forecast_error_message():
        info_message(get_forecast_error_message())
else:
    with st.expander("Shared SKU forecast input", expanded=False):
        st.dataframe(forecast[[column for column in ("SKU", "Product", "Category", "Time", "Forecast") if column in forecast.columns]], hide_index=True)

st.subheader("MCA readiness")
sales_velocity = analytics.get("sales_velocity")
if sales_velocity is not None and not sales_velocity.empty:
    with st.expander("Shared sales-velocity input", expanded=False):
        st.dataframe(sales_velocity, hide_index=True)

product_performance = analytics.get("product_performance")
if product_performance is not None and not product_performance.empty:
    return_columns = [column for column in ("Product Key", "SKU", "Product", "Category", "Returned Quantity", "Return Quantity Rate") if column in product_performance.columns]
    with st.expander("Shared product return and order measures", expanded=False):
        st.dataframe(product_performance[return_columns], hide_index=True)

mca = get_mca_results()
if mca is not None and not mca.empty:
    st.subheader("SKU Priority Score and criteria contributions")
    st.dataframe(mca, hide_index=True)
else:
    error_message = get_prescriptive_error_message()
    if error_message:
        info_message(error_message)
    else:
        info_message("MCA requires a complete SKU forecast and a fresh, unambiguous current-stock match.")
