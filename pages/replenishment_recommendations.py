"""Decision-support-only replenishment page backed by shared state."""

import pandas as pd
import streamlit as st

from utils.analytics_display import number
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, render_page_shell, section_header
from utils.state import (
    DataStatus,
    ensure_derived_outputs_for_active_dataset,
    get_analytics_results,
    get_data_status,
    get_prescriptive_error_message,
    get_recommendation_results,
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
PRIORITY_GROUPS = {
    "Immediate": "Urgent",
    "High": "Urgent",
    "Medium": "Recommended",
    "Low": "Recommended",
    "None": "Monitor",
}
ACTION_GROUPS = {
    "Replenish to target": "Recommended",
    "Maintain stock": "Monitor",
    "Monitor; no forecast demand": "Monitor",
}


def _clean_label(value: object) -> str | None:
    if pd.isna(value):
        return None
    label = str(value).strip()
    if not label or label.lower() == "nan":
        return None
    return label


def _recommendation_summary_group(row: pd.Series) -> str | None:
    priority = _clean_label(row.get("Recommendation Priority"))
    if priority in PRIORITY_GROUPS:
        return PRIORITY_GROUPS[priority]

    recommendation = _clean_label(row.get("Recommendation"))
    if recommendation in ACTION_GROUPS:
        return ACTION_GROUPS[recommendation]

    return None


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
ensure_derived_outputs_for_active_dataset()
render_page_shell("Replenishment Recommendations", "Decide - Prescriptive")

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
        st.markdown(
            "<div style='height: .75rem;'></div>",
            unsafe_allow_html=True,
        )
        section_header(
            "Replenishment Recommendations",
            "Review the current SKU-level replenishment recommendations generated from the active dataset.",
        )

        counts = _summary_counts(recommendations)

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

        st.dataframe(
            _display_recommendations(recommendations),
            hide_index=True,
            use_container_width=True,
        )

        if "Supplier Lead Time Source" in recommendations and recommendations["Supplier Lead Time Source"].astype(str).str.startswith("Fallback ").any():
            st.warning("At least one SKU uses the system fallback lead time. Confirm supplier lead times before acting on replenishment quantities.")

info_message("Decision-support only: outputs support business-owner review and do not place orders or modify Shopee inventory.")
