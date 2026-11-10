"""Pure display shaping helpers for product prioritization."""

import pandas as pd


RANKING_CRITERIA = (
    ("Sales Velocity", "Sales Velocity (units/day)"),
    ("Forecasted Demand", "Forecast Demand (units)"),
    ("Recorded Return/Refund Quantity Rate", "Return Rate (recorded units)"),
    ("Return Rate", "Return Rate"),
)


def ranking_table(frame: pd.DataFrame, why_text) -> pd.DataFrame:
    table = frame.rename(
        columns={
            "Priority Rank": "Rank",
            "SKU Priority Score": "MCA Score",
            "Priority Level": "Priority",
        }
    ).copy()
    table["Why Prioritized"] = table.apply(why_text, axis=1)
    criteria_columns = [
        source for source, _label in RANKING_CRITERIA if source in table.columns
    ]
    rename_criteria = {
        source: label
        for source, label in RANKING_CRITERIA
        if source in table.columns
    }
    table = table.rename(columns=rename_criteria)
    display_criteria = [rename_criteria[source] for source in criteria_columns]
    columns = ["Rank", "Product", "SKU", *display_criteria, "MCA Score", "Priority", "Why Prioritized"]
    return table[[column for column in columns if column in table.columns]]
