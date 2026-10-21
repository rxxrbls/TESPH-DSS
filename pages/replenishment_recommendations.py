"""Decision-support-only replenishment page backed by shared state."""

import streamlit as st

from utils.components import empty_state, guard_protected_page, info_message, render_page_shell
from utils.state import DataStatus, get_data_status, get_prescriptive_error_message, get_recommendation_results


guard_protected_page()
render_page_shell("Replenishment Recommendations", "Decide · Prescriptive")

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing replenishment.")
else:
    recommendations = get_recommendation_results()
    if recommendations is None or recommendations.empty:
        error_message = get_prescriptive_error_message()
        if error_message:
            info_message(error_message)
        else:
            info_message("Upload and validate current stock to calculate explainable SKU-level replenishment recommendations.")
    else:
        st.subheader("Replenishment recommendations")
        columns = [
            "SKU", "Product", "Category", "Stock-Out Risk", "Days of Inventory",
            "Risk Index", "Priority Level", "SKU Priority Score", "Priority Rank",
            "Current Stock", "Safety Stock", "Target Stock Level", "Recommended Quantity",
            "Recommendation Priority", "Recommendation", "Recommendation Explanation",
            "Supplier Lead Time", "Supplier Lead Time Source",
        ]
        st.dataframe(recommendations[[column for column in columns if column in recommendations]], hide_index=True)
        if "Supplier Lead Time Source" in recommendations and recommendations["Supplier Lead Time Source"].astype(str).str.startswith("Fallback ").any():
            st.warning("At least one SKU uses the system fallback lead time. Confirm supplier lead times before acting on replenishment quantities.")

info_message("Decision-support only: outputs support business-owner review and do not place orders or modify Shopee inventory.")
