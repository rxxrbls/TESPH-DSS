from src.prescriptive.recommendation_rules import (
    generate_recommendation,
    calculate_target_stock_level,
    calculate_replenishment_quantity,
)


# KAN-287 - VALIDATE RECOMMENDATION OUTPUTS

def test_high_priority_critical_risk():
    result = generate_recommendation(10, "Critical", "High")
    assert result == "Immediate Restock - Highest Priority"


def test_medium_priority_high_risk():
    result = generate_recommendation(10, "High", "Medium")
    assert result == "Restock"


def test_low_priority_low_risk():
    result = generate_recommendation(0, "Low", "Low")
    assert result == "Maintain Stock / Do Not Restock"


def test_no_immediate_demand_risk():
    result = generate_recommendation(
        0,
        "No Forecast Demand",
    )
    assert result == "No Immediate Restock / Monitor Demand"


def test_recommendation_matrix_high_priority_low_risk():
    assert generate_recommendation(10, "Low", "High") == "Maintain Stock / Monitor"


def test_recommendation_matrix_medium_priority_medium_risk():
    assert generate_recommendation(10, "Medium", "Medium") == "Monitor / Consider Restocking"


def test_recommendation_matrix_low_priority_critical_risk():
    assert generate_recommendation(10, "Critical", "Low") == "Restock / Review Immediately"


def test_all_approved_priority_risk_matrix_cells():
    expected = {
        ("High", "Critical"): "Immediate Restock - Highest Priority",
        ("High", "High"): "Restock - High Priority",
        ("High", "Medium"): "Restock Soon",
        ("High", "Low"): "Maintain Stock / Monitor",
        ("Medium", "Critical"): "Immediate Restock",
        ("Medium", "High"): "Restock",
        ("Medium", "Medium"): "Monitor / Consider Restocking",
        ("Medium", "Low"): "Maintain Stock",
        ("Low", "Critical"): "Restock / Review Immediately",
        ("Low", "High"): "Review for Restocking",
        ("Low", "Medium"): "Monitor",
        ("Low", "Low"): "Maintain Stock / Do Not Restock",
    }
    assert {
        key: generate_recommendation(10, key[1], key[0]) for key in expected
    } == expected


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
