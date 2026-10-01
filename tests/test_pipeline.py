"""Tests for the analytics and forecasting pipelines."""

import unittest

import numpy as np
import pandas as pd

from analytics_calculations import calculate_low_sales_threshold
from analytics_pipeline import (
    run_product_movement_analysis,
)
from forecasting_calculations import evaluate_category_eligibility
from forecasting_pipeline import (
    _find_best_es_alpha,
    _rolling_validation,
    run_forecasting_pipeline,
)
from methodology_config import (
    ForecastConfig,
    DEMAND_CONTRIBUTION_WEIGHT,
    ES_ALPHA_CANDIDATES,
    FORECAST_AGGREGATION,
    FORECAST_FREQUENCY,
    FORECAST_HORIZON,
    LOW_SALES_PERCENTILE,
    MA_WINDOW,
    MAPE_ZERO_ACTUAL_POLICY,
    MINIMUM_COMPLETENESS,
    MINIMUM_CONSISTENCY,
    MINIMUM_HISTORY_PERIODS,
    MOVEMENT_FAST_MIN_POSITIVE_PERIODS,
    MOVEMENT_FREQUENCY,
    MOVEMENT_RECENT_PERIODS,
    MOVEMENT_REGULAR_MIN_POSITIVE_PERIODS,
    PRIMARY_SELECTION_METRIC,
    REVENUE_CONTRIBUTION_WEIGHT,
    SEASONAL_CYCLE,
    SECONDARY_SELECTION_METRIC,
    VALIDATION_PERIODS,
)


def _sample_transactions() -> pd.DataFrame:
    """Minimal transactions that satisfy the analytics contract."""
    rows = []
    products = [
        ("P1", "Product 1", "SKU-1", "Category A"),
        ("P2", "Product 2", "SKU-2", "Category A"),
        ("P3", "Product 3", "SKU-3", "Category B"),
        ("P4", "Product 4", "SKU-4", "Category B"),
    ]
    # 3 complete months of data
    for month in range(1, 4):
        for i, (pk, pname, sku, cat) in enumerate(products):
            qty = (month + i) * 2  # Varying quantities
            rows.append({
                "Order ID": f"O-{month}-{i}",
                "Order Status": "Completed",
                "SKU Reference No.": sku,
                "Product Name": f"Raw {pname}",
                "product_key": pk,
                "final_base_product_name": pname,
                "final_category": cat,
                "order_date": f"2026-0{month}-15",
                "Quantity": qty,
                "Returned quantity": 0,
                "Deal Price": 10,
                "Total Buyer Payment": qty * 10,
                "is_completed": True,
                "is_cancelled": False,
                "is_returned": False,
            })
    return pd.DataFrame(rows)


class TestMethodologyConfig(unittest.TestCase):
    """Verify professor-confirmed values are set correctly."""

    def test_forecast_parameters(self) -> None:
        self.assertEqual(FORECAST_FREQUENCY, "D")
        self.assertEqual(FORECAST_HORIZON, 7)
        self.assertEqual(MA_WINDOW, 3)
        self.assertEqual(SEASONAL_CYCLE, 12)
        self.assertEqual(VALIDATION_PERIODS, 14)

    def test_movement_parameters(self) -> None:
        self.assertEqual(MOVEMENT_FREQUENCY, "M")
        self.assertEqual(MOVEMENT_RECENT_PERIODS, 3)
        self.assertEqual(MOVEMENT_FAST_MIN_POSITIVE_PERIODS, 3)
        self.assertEqual(MOVEMENT_REGULAR_MIN_POSITIVE_PERIODS, 2)

    def test_eligibility_parameters(self) -> None:
        self.assertEqual(MINIMUM_HISTORY_PERIODS, 24)
        self.assertAlmostEqual(MINIMUM_COMPLETENESS, 0.75)
        self.assertAlmostEqual(MINIMUM_CONSISTENCY, 0.75)
        self.assertAlmostEqual(DEMAND_CONTRIBUTION_WEIGHT, 0.50)
        self.assertAlmostEqual(REVENUE_CONTRIBUTION_WEIGHT, 0.50)

    def test_model_selection_parameters(self) -> None:
        self.assertEqual(PRIMARY_SELECTION_METRIC, "MAPE")
        self.assertEqual(SECONDARY_SELECTION_METRIC, "RMSE")
        self.assertEqual(MAPE_ZERO_ACTUAL_POLICY, "denominator_floor")
        self.assertEqual(FORECAST_AGGREGATION, "sum")

    def test_es_alpha_grid(self) -> None:
        self.assertEqual(len(ES_ALPHA_CANDIDATES), 9)
        self.assertAlmostEqual(ES_ALPHA_CANDIDATES[0], 0.1)
        self.assertAlmostEqual(ES_ALPHA_CANDIDATES[-1], 0.9)

    def test_low_sales_percentile(self) -> None:
        self.assertEqual(LOW_SALES_PERCENTILE, 25)


class TestLowSalesThreshold(unittest.TestCase):
    """Test the dynamic 25th-percentile low-sales threshold."""

    def test_threshold_per_category(self) -> None:
        metrics = pd.DataFrame({
            "Category": ["A", "A", "A", "A", "B", "B"],
            "Recent Demand": [10, 20, 30, 40, 5, 100],
            "Recent Average Demand": [3.3, 6.7, 10.0, 13.3, 1.7, 33.3],
        })
        result = calculate_low_sales_threshold(metrics)
        self.assertEqual(len(result), 2)  # One row per category
        self.assertIn("Category", result.columns)
        self.assertIn("Low Sales Threshold", result.columns)
        # Category A: 25th percentile of positive recent demand
        a_threshold = result.loc[result["Category"] == "A", "Low Sales Threshold"].iloc[0]
        self.assertAlmostEqual(a_threshold, np.percentile([10, 20, 30, 40], 25))

    def test_zero_demand_excluded(self) -> None:
        metrics = pd.DataFrame({
            "Category": ["A", "A"],
            "Recent Demand": [0.0, 0.0],
            "Recent Average Demand": [0.0, 0.0],
        })
        result = calculate_low_sales_threshold(metrics)
        self.assertTrue(result.empty)


class TestProductMovementPipeline(unittest.TestCase):
    """Test the product movement analysis pipeline."""

    def test_returns_expected_keys(self) -> None:
        txns = _sample_transactions()
        result = run_product_movement_analysis(txns)
        expected_keys = {"metrics", "classified", "thresholds", "for_review"}
        self.assertEqual(set(result.keys()), expected_keys)

    def test_classified_has_movement_column(self) -> None:
        txns = _sample_transactions()
        result = run_product_movement_analysis(txns)
        if not result["classified"].empty:
            self.assertIn("Movement Classification", result["classified"].columns)
            self.assertIn("Review Status", result["classified"].columns)
            valid_classes = {"Fast Moving", "Regular Moving", "Slow Moving", "No Movement"}
            actual_classes = set(result["classified"]["Movement Classification"].unique())
            self.assertTrue(actual_classes.issubset(valid_classes))

    def test_thresholds_are_per_category(self) -> None:
        txns = _sample_transactions()
        result = run_product_movement_analysis(txns)
        if not result["thresholds"].empty:
            self.assertIn("Category", result["thresholds"].columns)
            self.assertIn("Low Sales Threshold", result["thresholds"].columns)

    def test_incomplete_latest_month_is_excluded_from_recent_window(self) -> None:
        txns = _sample_transactions()
        result = run_product_movement_analysis(txns)
        self.assertLessEqual(
            int(result["metrics"]["Recent Positive-Demand Periods"].max()), 2
        )


def _monthly_transactions_with_incomplete_latest() -> pd.DataFrame:
    rows = []
    complete_months = pd.date_range("2024-01-01", periods=25, freq="MS")
    for index, month in enumerate(complete_months, start=1):
        order_date = (month + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        quantity = 10 + (index % 3)
        rows.append({
            "Order ID": f"C-{index}",
            "Order Status": "Completed",
            "SKU Reference No.": "SKU-A",
            "Product Name": "Raw Product A",
            "product_key": "P-A",
            "final_base_product_name": "Product A",
            "final_category": "Category A",
            "order_date": order_date,
            "Quantity": quantity,
            "Returned quantity": 0,
            "Deal Price": 10,
            "Total Buyer Payment": quantity * 10,
            "is_completed": True,
            "is_cancelled": False,
            "is_returned": False,
        })
    rows.append({
        "Order ID": "I-1",
        "Order Status": "Completed",
        "SKU Reference No.": "SKU-A",
        "Product Name": "Raw Product A",
        "product_key": "P-A",
        "final_base_product_name": "Product A",
        "final_category": "Category A",
        "order_date": "2026-02-15",
        "Quantity": 999,
        "Returned quantity": 0,
        "Deal Price": 10,
        "Total Buyer Payment": 9990,
        "is_completed": True,
        "is_cancelled": False,
        "is_returned": False,
    })
    return pd.DataFrame(rows)


class TestForecastingPipeline(unittest.TestCase):
    """Test the end-to-end forecasting orchestration rules."""

    def test_pipeline_excludes_incomplete_latest_month_before_forecasting(self) -> None:
        result = run_forecasting_pipeline(_monthly_transactions_with_incomplete_latest(), config=ForecastConfig(frequency="M", horizon=1))
        latest_forecast_history = result["forecasting_dataset"]["Time"].max()
        self.assertEqual(latest_forecast_history, pd.Timestamp("2026-01-01"))

    def test_category_eligibility_uses_latest_assessment_window(self) -> None:
        rows = []
        for index, time in enumerate(pd.date_range("2024-01-01", periods=30, freq="MS")):
            rows.append({
                "Time": time,
                "Category": "Category A",
                "Demand": 10.0 if index < 23 else 0.0,
                "Revenue": 100.0 if index < 23 else 0.0,
                "Observed": True,
            })
            rows.append({
                "Time": time,
                "Category": "Category B",
                "Demand": 10.0,
                "Revenue": 100.0,
                "Observed": True,
            })
        result = evaluate_category_eligibility(
            pd.DataFrame(rows),
            assessment_window=24,
            minimum_history_periods=24,
            minimum_completeness=0.75,
            minimum_consistency=0.75,
            demand_contribution_weight=0.5,
            revenue_contribution_weight=0.5,
        ).set_index("Category")

        self.assertFalse(bool(result.loc["Category A", "Eligible"]))
        self.assertEqual(result.loc["Category A", "Positive-Demand Periods"], 17)
        self.assertTrue(bool(result.loc["Category B", "Eligible"]))

    def test_rolling_validation_uses_latest_holdouts_without_leakage(self) -> None:
        data = pd.DataFrame({
            "Time": pd.date_range("2025-01-01", periods=6, freq="MS"),
            "Category": ["Category A"] * 6,
            "Demand": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "Revenue": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "Observed": [True] * 6,
        })
        detail = _rolling_validation(
            data,
            frequency="M",
            validation_periods=2,
            ma_window=3,
            best_alphas={"Category A": 0.5},
            seasonal_cycle=12,
        )
        moving = detail.loc[detail["Method"].eq("Moving Average")].sort_values("Time")

        self.assertEqual(
            moving["Time"].tolist(),
            [pd.Timestamp("2025-05-01"), pd.Timestamp("2025-06-01")],
        )
        self.assertEqual(moving["Forecast"].tolist(), [3.0, 4.0])

    def test_es_alpha_grid_search_uses_rolling_rmse(self) -> None:
        values = [10.0] * 12 + [20.0, 35.0, 55.0, 80.0, 110.0, 145.0]
        data = pd.DataFrame({
            "Time": pd.date_range("2025-01-01", periods=len(values), freq="MS"),
            "Category": ["Category A"] * len(values),
            "Demand": values,
            "Revenue": [value * 10 for value in values],
            "Observed": [True] * len(values),
        })

        expected_rmse = {}
        validation_periods = 6
        for alpha in ES_ALPHA_CANDIDATES:
            errors = []
            for holdout_index in range(len(values) - validation_periods, len(values)):
                train = values[:holdout_index]
                level = train[0]
                for actual in train[1:]:
                    level = alpha * actual + (1 - alpha) * level
                errors.append(values[holdout_index] - level)
            expected_rmse[alpha] = float(np.sqrt(np.mean(np.square(errors))))
        expected_alpha = min(expected_rmse, key=expected_rmse.get)

        result = _find_best_es_alpha(
            data,
            frequency="M",
            validation_periods=validation_periods,
        )

        self.assertEqual(result["Category A"], expected_alpha)


if __name__ == "__main__":
    unittest.main()
