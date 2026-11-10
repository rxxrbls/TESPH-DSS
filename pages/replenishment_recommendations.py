"""Decision-support-only replenishment page backed by shared state."""

import pandas as pd
import streamlit as st

from utils.analytics_display import number
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, render_page_shell, section_header
from utils.recommendation_filters import (
    filter_recommendations,
    recommendation_summary_group,
)
from utils.state import (
    DataStatus,
    ensure_derived_outputs_for_active_dataset,
    get_analytics_results,
    get_data_status,
    get_prescriptive_error_message,
    get_recommendation_results,
    get_inventory_validation,
    get_inventory_data,
    get_forecast_results,
)


DISPLAY_COLUMNS = [
    "Product",
    "SKU",
    "Current Stock",
    "Forecast Demand",
    "Risk",
    "Movement",
    "Recommended Qty",
    "Status",
]
URGENCY_FILTER_KEY = "replenishment_urgency_filter"
PRODUCT_SEARCH_KEY = "replenishment_product_search"


def _recommendation_summary_group(row: pd.Series) -> str | None:
    return recommendation_summary_group(row)


def _urgency_filter() -> str:
    options = ("All", "Urgent", "Recommended", "Monitor")
    return st.selectbox(
        "Urgency",
        options,
        key=URGENCY_FILTER_KEY,
        format_func=lambda value: "All" if value == "All" else value,
        label_visibility="collapsed",
    )


def _products_reviewed(recommendations: pd.DataFrame) -> int:
    for column in ("SKU", "Product"):
        if column in recommendations:
            values = recommendations[column].dropna().astype(str).str.strip()
            values = values.loc[values.ne("")]
            if not values.empty:
                return int(values.nunique())
    return int(len(recommendations))


def _summary_counts(recommendations: pd.DataFrame) -> dict[str, int]:
    groups = recommendations.apply(_recommendation_summary_group, axis=1)
    return {
        "Urgent": int(groups.eq("Urgent").sum()),
        "Recommended": int(groups.eq("Recommended").sum()),
        "Monitor": int(groups.eq("Monitor").sum()),
        "Products Reviewed": _products_reviewed(recommendations),
    }


def _with_movement(recommendations: pd.DataFrame) -> pd.DataFrame:
    display = recommendations.copy()
    if "Movement Classification" in display:
        return display

    analytics = get_analytics_results() or {}
    movement = analytics.get("movement_classified")
    if movement is None or movement.empty or "Movement Classification" not in movement:
        return display

    join_key = next(
        (
            column
            for column in ("Product Key", "SKU", "Product")
            if column in display.columns and column in movement.columns
        ),
        None,
    )
    if join_key is None:
        return display

    movement_lookup = (
        movement[[join_key, "Movement Classification"]]
        .dropna(subset=[join_key])
        .drop_duplicates(subset=[join_key])
    )
    return display.merge(movement_lookup, on=join_key, how="left")


def _display_recommendations(recommendations: pd.DataFrame) -> pd.DataFrame:
    source = _with_movement(recommendations)
    display = pd.DataFrame(index=source.index)
    display["Product"] = source.get("Product")
    display["SKU"] = source.get("SKU")
    display["Current Stock"] = source.get("Current Stock")
    display["Forecast Demand"] = source.get("Forecast Demand")
    display["Risk"] = source.get("Stock-Out Risk")
    display["Movement"] = source.get("Movement Classification")
    display["Recommended Qty"] = source.get("Recommended Quantity")
    display["Status"] = source.apply(_recommendation_summary_group, axis=1)
    return display.loc[:, DISPLAY_COLUMNS]


guard_protected_page()
ensure_derived_outputs_for_active_dataset(include_prescriptive=True)
render_page_shell("Replenishment Recommendations", "Decide - Prescriptive")
st.markdown(
    """
    <style>
    .replenishment-page-title { margin-top:0 !important; }
    div.st-key-replenishment_urgency_filter [data-baseweb="select"] > div {
        min-height:2.35rem !important;
        border:1px solid #E4DDD2 !important;
        border-radius:.6rem !important;
        background:#FFFFFF !important;
        box-shadow:none !important;
    }
    div.st-key-replenishment_urgency_filter [data-baseweb="select"] svg {
        background:transparent !important;
    }
    div.st-key-replenishment_product_search [data-testid="stTextInput"] [data-baseweb="input"],
    div.st-key-replenishment_product_search [data-testid="stTextInput"] [data-baseweb="base-input"] {
        background:#FFFFFF !important;
        border-color:#E4DDD2 !important;
        box-shadow:none !important;
    }
    div.st-key-replenishment_product_search [data-testid="stTextInput"] input {
        background:transparent !important;
    }
    div.st-key-replenishment_product_search [data-testid="stTextInput"] [data-baseweb="input"] svg {
        background:transparent !important;
        color:#625C54 !important;
        fill:currentColor !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing replenishment.")
else:
    recommendations = get_recommendation_results()
    if recommendations is None or recommendations.empty:
        error_message = get_prescriptive_error_message()
        if error_message:
            info_message(error_message)
        else:
            info_message("Current stock, stock-out risk, MCA, and replenishment are being prepared from the bundled TESPH data.")
    else:
        urgency = st.session_state.get(URGENCY_FILTER_KEY, "All")
        if urgency not in {"All", "Urgent", "Recommended", "Monitor"}:
            st.session_state[URGENCY_FILTER_KEY] = "All"
            urgency = st.session_state[URGENCY_FILTER_KEY]
        search_query = st.session_state.get(PRODUCT_SEARCH_KEY, "")
        if not isinstance(search_query, str):
            st.session_state[PRODUCT_SEARCH_KEY] = ""
            search_query = st.session_state[PRODUCT_SEARCH_KEY]
        filtered_recommendations = filter_recommendations(recommendations, urgency, search_query)
        if filtered_recommendations.empty:
            info_message("No recommendations match the selected urgency filter and search.")
        export = filtered_recommendations.copy()
        alias_map = {
            "SKU": "SKU", "Product": "Product Name", "Forecast Demand": "Forecast Demand",
            "Stock-Out Risk": "Stock-Out Risk", "Priority Level": "MCA Priority",
            "SKU Priority Score": "MCA Priority Score",
            "Recommendation": "Recommended Action", "Recommended Quantity": "Recommended Replenishment Quantity",
        }
        export = export.rename(columns={source: target for source, target in alias_map.items() if source in export})
        forecast_results = get_forecast_results()
        forecast_results = forecast_results if isinstance(forecast_results, dict) else {}
        inventory = get_inventory_data()
        inventory_validation = get_inventory_validation() or {}
        forecast_output = forecast_results.get("forecast_output")
        selection_status = forecast_results.get("selection_status")
        provisional = bool(forecast_output is None or getattr(forecast_output, "empty", True))
        if isinstance(selection_status, pd.DataFrame) and not selection_status.empty and "Historical Only" in selection_status:
            provisional = provisional or bool(selection_status["Historical Only"].fillna(True).any())
        else:
            provisional = True
        provisional = provisional or not bool(inventory_validation.get("valid", False))
        if isinstance(inventory, pd.DataFrame) and not inventory.empty and "stock_as_of" in inventory:
            stock_dates = pd.to_datetime(inventory["stock_as_of"], errors="coerce")
            provisional = provisional or (stock_dates.max() < pd.Timestamp.today().normalize())
            export["Inventory Stock As-Of"] = stock_dates.max()
        else:
            provisional = True
        if (recommendations.attrs.get("diagnostic") or recommendations.attrs.get("provisional")) if isinstance(recommendations.attrs, dict) else False:
            provisional = True
        if "MCA Status" in filtered_recommendations:
            provisional = provisional or filtered_recommendations["MCA Status"].astype(str).str.contains("unavailable|provisional|diagnostic", case=False, na=False).any()
        export["Output Status"] = "Diagnostic/provisional decision support" if provisional else "Decision support for business-owner review"
        has_fallback_lead_time = (
            "Supplier Lead Time Source" in filtered_recommendations
            and filtered_recommendations["Supplier Lead Time Source"].astype(str).str.startswith("Fallback ").any()
        )
        title_column, download_column = st.columns((4, 1), gap="small", vertical_alignment="center")
        with title_column:
            st.markdown(
                '<h2 class="section-title replenishment-page-title">Replenishment Recommendations</h2>'
                '<p class="section-description">Review the current SKU-level replenishment recommendations generated from the active dataset.</p>',
                unsafe_allow_html=True,
            )
        if not export.empty:
            with download_column:
                st.download_button(
                    "Download Purchase Plan (.csv)",
                    data=export.to_csv(index=False).encode("utf-8-sig"),
                    file_name="purchase_plan_diagnostic.csv",
                    mime="text/csv",
                    type="primary",
                    help="Exports calculated recommendations for review; this is not an approved supplier purchase order.",
                    width="stretch",
                )

        counts = _summary_counts(filtered_recommendations)

        for column, (label, value) in zip(
            st.columns(4, gap="small"),
            counts.items(),
            strict=True,
        ):
            with column:
                kpi_card(label, number(value))

        st.markdown(
            "<div style='height: 1.5rem;'></div>",
            unsafe_allow_html=True,
        )

        search_column, urgency_column = st.columns((1.8, 1), gap="small", vertical_alignment="bottom")
        with search_column:
            st.text_input(
                "Search SKU or product",
                key=PRODUCT_SEARCH_KEY,
                placeholder="Type part of a product name or SKU",
                icon=":material/search:",
                label_visibility="collapsed",
            )
        with urgency_column:
            _urgency_filter()

        if not filtered_recommendations.empty:
            st.dataframe(
                _display_recommendations(filtered_recommendations),
                hide_index=True,
                width="stretch",
            )
        if has_fallback_lead_time:
            st.warning("Decision-support only: outputs support business-owner review and do not place orders or modify Shopee inventory.")
