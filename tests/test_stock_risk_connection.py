from src.prescriptive.recommendation_rules import (
    generate_recommendation_from_risk_inputs,
)


# KAN-239 - CONNECT STOCK-OUT RISK OUTPUT


def test_critical_risk_is_consumed():
    result = generate_recommendation_from_risk_inputs(
        priority="High",
        current_stock=0,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    assert result["risk"] == "Critical"
    assert result["target_stock_level"] == 150
    assert result["recommended_quantity"] == 150
    assert result["recommendation_priority"] == "Immediate"
    assert result["recommendation"] == "Replenish to target"


def test_high_risk_is_consumed():
    # DOI = 50 / 10 = 5 days
    # Lead Time = 7 days
    # The configured seven-day DOI ceiling is Medium; action depends on quantity.
    result = generate_recommendation_from_risk_inputs(
        priority="Medium",
        current_stock=50,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    assert result["risk"] == "Medium"
    assert result["target_stock_level"] == 150
    assert result["recommended_quantity"] == 100
    assert result["recommendation_priority"] == "Medium"
    assert result["recommendation"] == "Replenish to target"


def test_no_demand_risk_is_consumed():
    result = generate_recommendation_from_risk_inputs(
        priority="High",
        current_stock=100,
        average_daily_forecast_demand=0,
        supplier_lead_time=7,
    )

    assert result["risk"] == "No Forecast Demand"
    assert result["recommended_quantity"] == 0
    assert result["recommendation_priority"] == "None"
    assert result["recommendation"] == "Monitor; no forecast demand"