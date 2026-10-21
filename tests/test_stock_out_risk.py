from src.prescriptive.recommendation_rules import (
    calculate_days_of_inventory,
    classify_stock_out_risk,
)


def test_doi_calculation():
    doi = calculate_days_of_inventory(
        current_stock=100,
        average_daily_forecast_demand=20,
    )

    assert doi == 5


def test_no_demand_risk():
    risk = classify_stock_out_risk(
        current_stock=100,
        average_daily_forecast_demand=0,
        supplier_lead_time=7,
    )

    assert risk == "No Forecast Demand"


def test_critical_risk():
    risk = classify_stock_out_risk(
        current_stock=0,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    assert risk == "Critical"


def test_high_risk_with_five_days_of_inventory_within_lead_time():
    risk = classify_stock_out_risk(
        current_stock=50,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    # DOI = 5
    assert risk == "High"


def test_high_risk_at_seven_day_lead_time_boundary():
    risk = classify_stock_out_risk(
        current_stock=70,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    # DOI = 7 = Lead Time
    assert risk == "High"


def test_medium_risk_above_lead_time():
    risk = classify_stock_out_risk(
        current_stock=80,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    # DOI = 8
    assert risk == "Medium"


def test_medium_risk_at_one_point_five_lead_time_boundary():
    risk = classify_stock_out_risk(
        current_stock=105,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    # DOI = 10.5 = 1.5 * Lead Time
    assert risk == "Medium"


def test_low_risk():
    risk = classify_stock_out_risk(
        current_stock=110,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    # DOI = 11 > 10.5
    assert risk == "Low"


def test_invalid_supplier_lead_time():
    try:
        classify_stock_out_risk(
            current_stock=100,
            average_daily_forecast_demand=10,
            supplier_lead_time=0,
        )
    except ValueError:
        assert True
    else:
        assert False
