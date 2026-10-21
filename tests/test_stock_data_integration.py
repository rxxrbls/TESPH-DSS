from datetime import date, timedelta

from methodology_config import REPLENISHMENT_CONFIG
from src.prescriptive.stock_data import (
    load_current_stock,
    calculate_stock_risk_from_approved_source,
)
from utils.stock_validation import STOCK_RECENCY_THRESHOLD_DAYS, validate_stock_as_of


def test_stock_recency_default_uses_configured_maximum_age():
    threshold = REPLENISHMENT_CONFIG.max_stock_age_days
    today = date.today()

    assert STOCK_RECENCY_THRESHOLD_DAYS == threshold
    assert not validate_stock_as_of(today - timedelta(days=threshold))["is_stale"]
    assert validate_stock_as_of(today - timedelta(days=threshold + 1))["is_stale"]


def test_missing_and_future_stock_dates_are_rejected():
    today = date.today()

    missing = validate_stock_as_of(None)
    future = validate_stock_as_of(today + timedelta(days=1))

    assert missing["valid"] is False
    assert "Stock As-Of Date is required" in missing["issues"]
    assert future["valid"] is False
    assert "Stock As-Of Date cannot be in the future" in future["issues"]


def test_approved_stock_source_loads():
    stock_df = load_current_stock()

    assert not stock_df.empty
    assert "product_key" in stock_df.columns
    assert "Current Stock" in stock_df.columns
    assert "Stock As-Of Date" in stock_df.columns


def test_approved_stock_date():
    stock_df = load_current_stock()

    assert (
        stock_df["Stock As-Of Date"]
        .dt.strftime("%Y-%m-%d")
        .eq("2026-09-09")
        .all()
    )

def test_stock_source_connects_to_risk_calculation():
    stock_df = load_current_stock()

    product_key = stock_df.iloc[0]["product_key"]
    expected_stock = stock_df.iloc[0]["Current Stock"]

    result = calculate_stock_risk_from_approved_source(
        product_key=product_key,
        average_daily_forecast_demand=10,
        supplier_lead_time=7,
    )

    assert result["product_key"] == product_key
    assert result["current_stock"] == expected_stock
    assert result["risk"] in {
        "Critical",
        "High",
        "Medium",
        "Low",
        "No Forecast Demand",
    }
