"""MCA product-priority page using shared application state."""

import streamlit as st
import pandas as pd
from methodology_config import MCA_CRITERIA
from utils.state import get_mca_audit

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
audit = get_mca_audit()
from three_criterion_mca import CRITERIA as THREE_CRITERIA, RATE
is_three = audit is not None and RATE in audit
display_criteria = THREE_CRITERIA if is_three else MCA_CRITERIA
if is_three:
    st.caption("Three-criterion MCA: Sales Velocity, Forecasted Demand, and Recorded Return/Refund Quantity Rate (%). TA-approved equal-third baseline weights; expanded-period checks and final TA validation pending. Complete eligible SKUs only; Min-Max normalization, valid constant criteria = 0.5, missing/unresolved criteria = N/A and exclusion. Selected request-date coverage is not lifetime return history.")
else:
    st.caption("Legacy five criteria: Sales Velocity, Profit Margin, Supplier Lead Time, Forecasted Demand, Return Rate. Upload the cleaned return/refund evidence under Data Upload to activate the conditionally approved three-criterion assessment. Legacy weights: 20% each.")
if audit is not None and not audit.empty:
    # Explicit display strings: the grid renders numeric nulls as None even
    # when a Styler provides N/A. Keep the downloadable audit numeric.
    display_audit = audit.copy()
    for criterion in display_criteria:
        display_audit[criterion] = audit[criterion].map(
            lambda value: "N/A" if pd.isna(value) else format(value, ".6g")
        )
    st.dataframe(display_audit, hide_index=True)
    st.download_button("Download MCA readiness audit", audit.to_csv(index=False), "mca_readiness.csv", "text/csv")
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
    st.download_button("Download MCA rankings", mca.to_csv(index=False), "mca_rankings.csv", "text/csv")
else:
    error_message = get_prescriptive_error_message()
    if error_message:
        info_message(error_message)
    else:
        info_message("For the three-criterion assessment, connect sales, current stock and forecasts, then upload cleaned return/refund evidence with explicit coverage dates. Missing or unresolved criteria remain unavailable. Product costs and supplier lead times are not required for three-criterion MCA.")

comparison = st.session_state.get("mca_sensitivity")
if is_three and comparison is not None:
    st.subheader("Provisional weight sensitivity")
    st.dataframe(comparison, hide_index=True)
    st.download_button("Download weight comparison", comparison.to_csv(index=False), "mca_weight_comparison.csv", "text/csv")
