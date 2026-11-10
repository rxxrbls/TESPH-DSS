"""Decision-support overview backed by the processed session dataset."""

import streamlit as st

from utils.analytics_display import currency, number, render_category_mix, render_priority_recommendations, render_product_performance, render_sales_trend
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, primary_button, render_page_shell, section_header
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_error_message, get_analytics_results, get_data_status, get_recommendation_results, get_risk_results


guard_protected_page()
render_page_shell("Dashboard", "Overview")
ensure_derived_outputs_for_active_dataset(include_forecast=False)
st.markdown(
    """
    <style>
    [data-testid="stElementContainer"]:has(.dashboard-second-row-anchor) {
        height: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }

    [data-testid="stElementContainer"]:has(.dashboard-second-row-anchor)
    + [data-testid="stHorizontalBlock"] .dashboard-recommendations-title {
        margin-top: .5rem !important;
    }

    .dashboard-top-title {
        margin-top: 0 !important;
    }

    .dashboard-recommendations-title {
        margin-bottom: .12rem !important;
    }
    div.st-key-view_all_recommendations {
    display: flex !important;
    justify-content: flex-end !important;
    align-items: center !important;
    margin: 0 !important;
    transform: translateY(1.15rem);
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

risk_data = get_risk_results()
recommendation_data = get_recommendation_results()
high_count = 0
immediate_count = 0
if risk_data is not None and not risk_data.empty and "Stock-Out Risk" in risk_data.columns:
    high_count = int(risk_data["Stock-Out Risk"].astype("string").eq("High").fillna(False).sum())
if recommendation_data is not None and not recommendation_data.empty and "Recommendation Priority" in recommendation_data.columns:
    immediate_count = int(recommendation_data["Recommendation Priority"].astype("string").eq("Immediate").fillna(False).sum())
if high_count or immediate_count:
    st.warning(
        f"Immediate Action Required: {high_count} High stock-out risk item(s) and {immediate_count} Immediate-priority recommendation(s) detected. "
        "Navigate to **Replenishment Recommendations** to review purchasing quantities."
    )
summary = analytics["sales_summary"].iloc[0]
st.markdown(
    '<h2 class="section-title dashboard-top-title">Store Overview</h2>'
    '<p class="section-description">A current view of the processed Shopee transaction dataset.</p>',
    unsafe_allow_html=True,
)
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
        "Sales Trend",
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
        "Category Mix",
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
        "Product Performance",
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
        title_column, view_all_column = st.columns(
            (1.4, .24),
            gap="small",
            vertical_alignment="center",
        )
        with title_column:
            st.markdown(
                '<h2 class="section-title dashboard-recommendations-title">Priority Recommendations</h2>',
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
            "Priority Recommendations",
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
