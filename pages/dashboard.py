"""Decision-support overview backed by the processed session dataset."""

import streamlit as st

from utils.analytics_display import currency, number, render_category_mix, render_priority_recommendations, render_product_performance, render_sales_trend
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, primary_button, render_page_shell, section_header
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_error_message, get_analytics_results, get_data_status, get_recommendation_results


guard_protected_page()
ensure_derived_outputs_for_active_dataset()
render_page_shell("Dashboard", "Overview")

st.markdown(
    """
    <style>
    [data-testid="stElementContainer"]:has(.dashboard-second-row-anchor) {
        height: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }

    [data-testid="stElementContainer"]:has(.dashboard-second-row-anchor)
    + [data-testid="stHorizontalBlock"] .section-title {
        margin-top: .5rem !important;
    }
    div.st-key-view_all_recommendations {
    display: flex !important;
    justify-content: flex-end !important;
    margin-top: 1.85rem !important;
    margin-left: 3rem !important;
    }

    div.st-key-view_all_recommendations .stButton > button[kind="secondary"],
    div.st-key-view_all_recommendations button[kind="secondary"],
    div.st-key-view_all_recommendations button[kind="secondary"] p {
        min-height: auto !important;
        height: auto !important;
        padding: 0 !important;

        background: transparent !important;
        background-color: transparent !important;
        background-image: none !important;

        border: 0 !important;
        outline: 0 !important;
        box-shadow: none !important;

        color: var(--tesph-brand) !important;
        font-size: .82rem !important;
        font-weight: 800 !important;
        line-height: 1.2 !important;
        cursor: pointer !important;
    }

    div.st-key-view_all_recommendations .stButton > button[kind="secondary"]:hover,
    div.st-key-view_all_recommendations .stButton > button[kind="secondary"]:focus,
    div.st-key-view_all_recommendations .stButton > button[kind="secondary"]:focus-visible,
    div.st-key-view_all_recommendations .stButton > button[kind="secondary"]:active,
    div.st-key-view_all_recommendations button[kind="secondary"]:hover,
    div.st-key-view_all_recommendations button[kind="secondary"]:focus,
    div.st-key-view_all_recommendations button[kind="secondary"]:focus-visible,
    div.st-key-view_all_recommendations button[kind="secondary"]:active {
        background: transparent !important;
        background-color: transparent !important;
        background-image: none !important;

        border: 0 !important;
        outline: 0 !important;
        box-shadow: none !important;

        color: var(--tesph-brand-strong) !important;
    }

    /* ONLY change text color on hover/focus/click */
    div.st-key-view_all_recommendations button:hover *,
    div.st-key-view_all_recommendations button:hover p,
    div.st-key-view_all_recommendations button:focus *,
    div.st-key-view_all_recommendations button:focus p,
    div.st-key-view_all_recommendations button:focus-visible *,
    div.st-key-view_all_recommendations button:focus-visible p,
    div.st-key-view_all_recommendations button:active *,
    div.st-key-view_all_recommendations button:active p {
        color: var(--tesph-brand-strong) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    ("Gross revenue", currency(summary["Gross Revenue"]), False),
    ("Total orders", number(summary["Order Count"]), False),
    ("Products", number(summary["Product Count"]), False),
    ("Average order value", currency(summary["Average Order Value"]), False),
)
for column, (label, value, accent) in zip(st.columns(4, gap="small"), kpis, strict=True):
    with column:
        kpi_card(label, value, accent=accent)

trend_column, mix_column = st.columns((1.45, 1), gap="medium")

with trend_column:
    section_header(
        "Sales trend",
        "Monthly net revenue after returns, grouped by category.",
    )
    if not render_sales_trend(
        analytics.get("sales_trends"),
        height=360,
    ):
        info_message(
            "Sales trend data is unavailable for this processed dataset."
        )

with mix_column:
    section_header(
        "Category mix",
        "Share of revenue by category.",
    )
    if not render_category_mix(
        analytics.get("sales_trends"),
        height=360,
    ):
        info_message(
            "Category mix data is unavailable for this processed dataset."
        )

st.markdown(
    '<span class="dashboard-second-row-anchor" aria-hidden="true"></span>',
    unsafe_allow_html=True,
)

products_column, recommendations_column = st.columns(
    (1.35, 1),
    gap="medium",
)

with products_column:
    section_header(
        "Product performance",
        "Top products by gross revenue.",
    )
    if not render_product_performance(
        analytics.get("product_performance"),
        height=310,
    ):
        info_message(
            "Product performance data is unavailable for this processed dataset."
        )

with recommendations_column:
    recommendations = get_recommendation_results()
    recommendations_available = recommendations is not None and not recommendations.empty

    if recommendations_available:
        title_column, view_all_column = st.columns((1, .34), gap="small")
        with title_column:
            st.markdown(
                '<h2 class="section-title">Priority recommendations</h2>',
                unsafe_allow_html=True,
            )
        with view_all_column:
            if st.button(
                "View all >",
                key="view_all_recommendations",
            ):
                st.switch_page("pages/replenishment_recommendations.py")
        st.markdown(
            '<p class="section-description">Priority actions for replenishment.</p>',
            unsafe_allow_html=True,
        )
    else:
        section_header(
            "Priority recommendations",
            "Priority actions for replenishment.",
        )

    if not render_priority_recommendations(
        recommendations,
        height=310,
    ):
        info_message(
            "Priority recommendations are unavailable because "
            "replenishment recommendations are not available."
        )
