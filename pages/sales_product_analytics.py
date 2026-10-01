"""Descriptive sales and product analytics from the approved analytics pipeline."""

import pandas as pd
import streamlit as st

from utils.analytics_display import currency, number, percent, render_product_performance, render_sales_trend
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, primary_button, render_page_shell, section_header
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_error_message, get_analytics_results, get_data_status


def _table(frame: pd.DataFrame | None, *, limit: int | None = None) -> bool:
    """Show an existing output table without creating substitute values."""
    if frame is None or frame.empty:
        return False
    st.dataframe(frame.head(limit) if limit else frame, use_container_width=True, hide_index=True)
    return True


guard_protected_page()
render_page_shell("Sales & Product Analytics", "Analyze · Descriptive")
ensure_derived_outputs_for_active_dataset()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available yet", "Upload and process a Shopee transaction file to view sales and product analytics.", "Data")
    if primary_button("Upload data", key="analytics_go_to_upload"):
        st.switch_page("pages/data_upload.py")
    st.stop()

analytics = get_analytics_results()
if not analytics or analytics.get("sales_summary") is None or analytics["sales_summary"].empty:
    empty_state("Analytics are not available", "The processed dataset is present, but descriptive analytics could not be prepared for this session.", "Data")
    if get_analytics_error_message():
        info_message(get_analytics_error_message())
    st.stop()

summary = analytics["sales_summary"].iloc[0]
section_header("Sales summary", "Real metrics from the current processed transaction dataset.")
summary_cards = (
    ("Gross revenue", currency(summary["Gross Revenue"]), True),
    ("Net revenue after returns", currency(summary["Net Revenue After Returns"]), False),
    ("Gross demand", number(summary["Gross Demand"]), False),
    ("Return quantity rate", percent(summary["Return Quantity Rate"]), False),
    ("Cancellation order rate", percent(summary["Cancellation Order Rate"]), False),
)
for column, (label, value, accent) in zip(st.columns(5, gap="small"), summary_cards, strict=True):
    with column:
        kpi_card(label, value, accent=accent)

section_header("Product performance", "Products are ranked by gross revenue; quantities and returns remain visible in the detail table.")
products = analytics.get("product_performance")
if render_product_performance(products, height=340):
    with st.expander("Product performance detail", expanded=False):
        _table(products, limit=100)
else:
    info_message("Product performance data is unavailable for this processed dataset.")

section_header("Sales trends", "Monthly category trends using net revenue after returns.")
if not render_sales_trend(analytics.get("sales_trends"), height=340):
    info_message("Sales trend data is unavailable for this processed dataset.")

returns_column, cancellations_column = st.columns(2, gap="large")
with returns_column:
    section_header("Returns", "Return indicators from order and returned-quantity statuses.")
    returns = analytics.get("return_indicators")
    if returns is not None and not returns.empty:
        return_summary = returns.iloc[0]
        cols = st.columns(2)
        with cols[0]:
            kpi_card("Returned quantity", number(return_summary["Returned Quantity"]), accent=True)
        with cols[1]:
            kpi_card("Return order rate", percent(return_summary["Return Order Rate"]))
        category_returns = analytics.get("return_indicators_by_category")
        if category_returns is not None and not category_returns.empty:
            with st.expander("Returns by category", expanded=False):
                _table(category_returns)
    else:
        info_message("Return indicators are unavailable for this processed dataset.")

with cancellations_column:
    section_header("Cancellations", "Order-status indicators supplied by descriptive analytics.")
    status = analytics.get("order_status")
    cancellation_rows = pd.DataFrame()
    if status is not None and "Order Status" in status.columns:
        cancellation_rows = status.loc[status["Order Status"].astype("string").str.contains("cancel", case=False, na=False)]
    if cancellation_rows.empty:
        info_message("No cancelled orders were recorded in the processed dataset.")
    else:
        cancellation = cancellation_rows.iloc[0]
        cols = st.columns(2)
        with cols[0]:
            kpi_card("Cancelled orders", number(cancellation["Order Count"]), accent=True)
        with cols[1]:
            kpi_card("Cancelled quantity", number(cancellation["Quantity"]))
        with st.expander("Cancellation detail", expanded=False):
            _table(cancellation_rows)

section_header("Product movement", "Movement classifications and review flags returned by the approved product-movement analysis.")
movement = analytics.get("movement_classified")
if movement is None or movement.empty:
    info_message("Product movement needs sufficient complete transaction history; no movement output is available for this dataset.")
else:
    classification_counts = movement["Movement Classification"].value_counts(dropna=False).rename_axis("Movement classification").reset_index(name="Products")
    st.dataframe(classification_counts, use_container_width=True, hide_index=True)
    with st.expander("Product movement detail", expanded=False):
        _table(movement)
