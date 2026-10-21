"""Compatibility exports for the authoritative risk and replenishment math."""

import pandas as pd

from methodology_config import FORECAST_HORIZON, REPLENISHMENT_CONFIG, STOCK_RISK_THRESHOLDS
from prescriptive_calculations import (
    calculate_days_of_inventory as _calculate_days_of_inventory,
    calculate_replenishment_quantity,
    calculate_safety_stock,
    calculate_stock_out_risk,
    calculate_target_stock_level as _calculate_target_stock_level,
    classify_mca_priority as _classify_mca_priority,
    classify_recommendation_priority,
    recommendation_action as _recommendation_action,
)

RISK_CRITICAL = "Critical"
RISK_HIGH = "High"
RISK_MEDIUM = "Medium"
RISK_LOW = "Low"
RISK_NO_DEMAND = "No Forecast Demand"

def classify_stock_out_risk(
    current_stock,
    average_daily_forecast_demand,
    supplier_lead_time=None,
):
    """Compatibility adapter using a supplied or configured supplier lead time."""

    lead_time = (
        REPLENISHMENT_CONFIG.supplier_lead_time_days
        if supplier_lead_time is None
        else supplier_lead_time
    )
    forecast_demand = average_daily_forecast_demand * FORECAST_HORIZON
    result = calculate_stock_out_risk(
        pd.DataFrame({"SKU": ["SKU"], "Forecast": [forecast_demand]}),
        pd.DataFrame({
            "SKU": ["SKU"],
            "Current Stock": [current_stock],
            "Supplier Lead Time": [lead_time],
        }),
        item_columns=["SKU"],
        forecast_horizon_days=FORECAST_HORIZON,
        thresholds=STOCK_RISK_THRESHOLDS,
    )
    return str(result.iloc[0]["Stock-Out Risk"])

# W1-60 / KAN-251 - DAYS OF INVENTORY
def calculate_days_of_inventory(
    current_stock,
    average_daily_forecast_demand,
):
    """
    DOI = Current Stock / Average Daily Forecast Demand
    """

    return _calculate_days_of_inventory(current_stock, average_daily_forecast_demand)

def classify_mca_priority(priority_rank, total_skus):
    """Classify one SKU by its rank within the scored SKU population."""

    return _classify_mca_priority(priority_rank, total_skus)

def generate_recommendation(recommended_quantity, risk, mca_priority=None):
    """Compatibility name for the shared action-label rule."""

    return _recommendation_action(recommended_quantity, risk, mca_priority)

# KAN-239 - CONNECT STOCK-OUT RISK OUTPUT
def generate_recommendation_from_risk_inputs(
    priority,
    current_stock,
    average_daily_forecast_demand,
    supplier_lead_time,
):
    """
    Compatibility adapter that applies the shared replenishment calculations.
    """

    risk = classify_stock_out_risk(current_stock, average_daily_forecast_demand, supplier_lead_time)
    forecast_demand = average_daily_forecast_demand * FORECAST_HORIZON
    target_stock_level = calculate_target_stock_level(
        forecast_demand,
        forecast_horizon_days=FORECAST_HORIZON,
        lead_time_days=supplier_lead_time,
    )
    recommended_quantity = calculate_replenishment_quantity(
        target_stock_level, current_stock
    )

    return {
        "risk": risk,
        "target_stock_level": target_stock_level,
        "recommended_quantity": recommended_quantity,
        "recommendation": generate_recommendation(recommended_quantity, risk, priority),
        "recommendation_priority": classify_recommendation_priority(
            recommended_quantity, risk, priority
        ),
    }

# KAN-285 - IMPLEMENT TARGET STOCK LEVEL
def calculate_target_stock_level(
    forecast_demand,
    *,
    forecast_horizon_days=FORECAST_HORIZON,
    lead_time_days=REPLENISHMENT_CONFIG.supplier_lead_time_days,
    review_period_days=REPLENISHMENT_CONFIG.review_period_days,
    safety_stock_days=REPLENISHMENT_CONFIG.safety_stock_days,
):
    """Compatibility entry point for the shared forecast-cover target formula."""

    return _calculate_target_stock_level(
        forecast_demand,
        forecast_horizon_days=forecast_horizon_days,
        lead_time_days=lead_time_days,
        review_period_days=review_period_days,
        safety_stock_days=safety_stock_days,
    )

# W1-62 / KAN-286 - IMPLEMENT REPLENISHMENT QUANTITY
calculate_replenishment_quantity = calculate_replenishment_quantity

# W1-63 / KAN-139 - STANDARDIZED RECOMMENDATION OUTPUT
def create_recommendation_output(
    sku,
    product,
    priority,
    risk,
    recommendation,
    recommended_quantity,
    reason,
):
    """
    Creates the standardized prescriptive recommendation output.

    The recommendation, risk classification, and replenishment
    quantity are calculated by their respective prescriptive
    functions and passed to this function for dashboard output.
    """

    return {
        "sku": sku,
        "product": product,
        "priority": priority,
        "risk": risk,
        "recommendation": recommendation,
        "recommended_quantity": recommended_quantity,
        "reason": reason,
    }
