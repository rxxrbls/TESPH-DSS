"""Pure record filtering helpers for the stock-out risk page."""

import math

import pandas as pd


def calculate_days_of_supply(current_stock: object, forecast_demand: object) -> float | str:
    """Estimate days of stock cover from the seven-day forecast total."""
    try:
        stock = float(current_stock)
        demand = float(forecast_demand)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(stock) or not math.isfinite(demand):
        return "N/A"
    if demand == 0:
        return "N/A — No Forecast Demand"
    if demand < 0 or stock < 0:
        return "N/A"
    return round(stock / (demand / 7.0), 1)


def filter_risk_records(base: pd.DataFrame, priority_level: str = "All", query: str = "") -> pd.DataFrame:
    result = base.copy()
    if priority_level == "No Forecast Demand":
        if "Stock-Out Risk" not in result:
            return result.iloc[0:0]
        result = result.loc[
            result["Stock-Out Risk"].astype("string").eq(priority_level).fillna(False)
        ]
    elif priority_level != "All":
        if "Priority Level" not in result:
            return result.iloc[0:0]
        result = result.loc[
            result["Priority Level"].astype("string").eq(priority_level).fillna(False)
        ]
    if query.strip():
        searchable = pd.Series("", index=result.index)
        for column in ("SKU", "Product"):
            if column in result:
                searchable = searchable + " " + result[column].astype("string").fillna("")
        result = result.loc[searchable.str.contains(query.strip(), case=False, regex=False, na=False)]
    return result
