"""Pure urgency grouping and search helpers for recommendations."""

import pandas as pd


PRIORITY_GROUPS = {
    "Immediate": "Urgent",
    "High": "Urgent",
    "Medium": "Recommended",
    "Low": "Recommended",
    "None": "Monitor",
}
ACTION_GROUPS = {
    "Immediate Restock": "Urgent",
    "Immediate Restock - Highest Priority": "Urgent",
    "Restock - High Priority": "Urgent",
    "Restock / Review Immediately": "Urgent",
    "Restock Soon": "Recommended",
    "Restock": "Recommended",
    "Replenish to target": "Recommended",
    "Review for Restocking": "Recommended",
    "Monitor / Consider Restocking": "Recommended",
    "Maintain Stock / Monitor": "Monitor",
    "Monitor": "Monitor",
    "Maintain stock": "Monitor",
    "Monitor; no forecast demand": "Monitor",
    "No Immediate Restock / Monitor Demand": "Monitor",
    "Maintain Stock": "Monitor",
    "Maintain Stock / Do Not Restock": "Monitor",
}


def recommendation_summary_group(row: pd.Series) -> str | None:
    priority = row.get("Recommendation Priority")
    if not pd.isna(priority):
        priority = str(priority).strip()
        if priority in PRIORITY_GROUPS:
            return PRIORITY_GROUPS[priority]
    action = row.get("Recommendation")
    if not pd.isna(action):
        return ACTION_GROUPS.get(str(action).strip())
    return None


def filter_recommendations(recommendations: pd.DataFrame, urgency: str = "All", query: str = "") -> pd.DataFrame:
    result = recommendations.copy()
    if urgency not in {"All", "Urgent", "Recommended", "Monitor"}:
        urgency = "All"
    if urgency != "All":
        groups = result.apply(recommendation_summary_group, axis=1)
        result = result.loc[groups.eq(urgency)]
    if query.strip():
        searchable = pd.Series("", index=result.index)
        for column in ("SKU", "Product"):
            if column in result:
                searchable = searchable + " " + result[column].astype("string").fillna("")
        result = result.loc[searchable.str.contains(query.strip(), case=False, regex=False, na=False)]
    return result
