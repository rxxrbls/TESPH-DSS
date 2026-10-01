import pandas as pd

from analytics.derived_metrics import DerivedMetricsCalculator


def test_stock_out_frequency_counts_distinct_events():
    stock_history = pd.DataFrame(
        {
            "product_key": [
                "prd_001",
                "prd_001",
                "prd_001",
                "prd_001",
                "prd_001",
                "prd_001",
            ],
            "Stock As-Of Date": [
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-04",
                "2026-09-05",
                "2026-09-06",
            ],
            "Current Stock": [
                10,
                5,
                0,
                0,
                8,
                0,
            ],
        }
    )

    result = (
        DerivedMetricsCalculator
        .calculate_stock_out_frequency(stock_history)
    )

    assert result.loc[0, "product_key"] == "prd_001"
    assert result.loc[0, "stock_out_frequency"] == 2


def test_consecutive_zero_stock_counts_once():
    stock_history = pd.DataFrame(
        {
            "product_key": [
                "prd_001",
                "prd_001",
                "prd_001",
                "prd_001",
            ],
            "Stock As-Of Date": [
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-04",
            ],
            "Current Stock": [
                10,
                0,
                0,
                0,
            ],
        }
    )

    result = (
        DerivedMetricsCalculator
        .calculate_stock_out_frequency(stock_history)
    )

    assert result.loc[0, "stock_out_frequency"] == 1


def test_product_with_no_stock_out_returns_zero():
    stock_history = pd.DataFrame(
        {
            "product_key": [
                "prd_001",
                "prd_001",
                "prd_001",
            ],
            "Stock As-Of Date": [
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
            ],
            "Current Stock": [
                10,
                8,
                4,
            ],
        }
    )

    result = (
        DerivedMetricsCalculator
        .calculate_stock_out_frequency(stock_history)
    )

    assert result.loc[0, "stock_out_frequency"] == 0