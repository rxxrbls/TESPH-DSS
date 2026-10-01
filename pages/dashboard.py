"""Decision-support overview backed by the processed session dataset."""

import streamlit as st

from utils.analytics_display import currency, number, render_product_performance, render_risk_summary, render_sales_trend
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, primary_button, render_page_shell, section_header
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_error_message, get_analytics_results, get_data_status, get_risk_results


guard_protected_page()
render_page_shell("Dashboard", "Overview")
ensure_derived_outputs_for_active_dataset()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available yet", "Upload your Shopee transaction file to begin analysis.", "Data")
    left, action, right = st.columns([1, 1.15, 1])
    with action:
        if primary_button("Upload data", key="go_to_upload"):
            st.switch_page("pages/data_upload.py")
    st.stop()

analytics = get_analytics_results()
if not analytics or analytics.get("sales_summary") is None or analytics["sales_summary"].empty:
    empty_state("Analytics are not available", "Your transaction data completed ETL, but the descriptive analytics output is unavailable for this session.", "Data")
    if get_analytics_error_message():
        info_message(get_analytics_error_message())
    st.stop()

summary = analytics["sales_summary"].iloc[0]
section_header("Store overview", "A current view of the processed Shopee transaction dataset.")
kpis = (
    ("Gross revenue", currency(summary["Gross Revenue"]), True),
    ("Total orders", number(summary["Order Count"]), False),
    ("Products", number(summary["Product Count"]), False),
    ("Average order value", currency(summary["Average Order Value"]), False),
)
for column, (label, value, accent) in zip(st.columns(4, gap="small"), kpis, strict=True):
    with column:
        kpi_card(label, value, accent=accent)

section_header("Sales trend", "Monthly net revenue after returns, grouped by the categories supplied by analytics.")
if not render_sales_trend(analytics.get("sales_trends")):
    info_message("Sales trend data is unavailable for this processed dataset.")

products_column, risk_column = st.columns((1.35, 1), gap="large")
with products_column:
    section_header("Product performance", "Top products by gross revenue.")
    if not render_product_performance(analytics.get("product_performance"), height=310):
        info_message("Product performance data is unavailable for this processed dataset.")
with risk_column:
    section_header("Risk summary", "Stock-out levels are shown only when supplied by the predictive risk module.")
    if not render_risk_summary(get_risk_results(), height=310):
        info_message("Risk assessment is not available yet. Uploading transaction data does not create stock-out risk levels; this awaits the approved predictive/risk output.")
