from src.prescriptive.recommendation_rules import (
    generate_recommendation,
    calculate_target_stock_level,
    calculate_replenishment_quantity,
)


# KAN-287 - VALIDATE RECOMMENDATION OUTPUTS

def test_high_priority_critical_risk():
    result = generate_recommendation(10, "Critical")
    assert result == "Replenish to target"


def test_medium_priority_high_risk():
    result = generate_recommendation(10, "High")
    assert result == "Replenish to target"


def test_low_priority_low_risk():
    result = generate_recommendation(0, "Low")
    assert result == "Maintain stock"


def test_no_immediate_demand_risk():
    result = generate_recommendation(
        0,
        "No Forecast Demand",
    )
    assert result == "Monitor; no forecast demand"


# KAN-287 - VALIDATE TARGET STOCK LEVEL

def test_target_stock_level():
    result = calculate_target_stock_level(
        forecast_demand=100,
        forecast_horizon_days=10,
        lead_time_days=5,
        review_period_days=5,
        safety_stock_days=2,
    )
    assert result == 120


# KAN-287 - VALIDATE REPLENISHMENT QUANTITY

def test_replenishment_quantity():
    result = calculate_replenishment_quantity(
        target_stock_level=120,
        current_stock=45,
    )
    assert result == 75


def test_no_replenishment_when_stock_is_sufficient():
    result = calculate_replenishment_quantity(
        target_stock_level=120,
        current_stock=150,
    )
    assert result == 0


def test_zero_stock():
    result = calculate_replenishment_quantity(
        target_stock_level=120,
        current_stock=0,
    )
    assert result == 120