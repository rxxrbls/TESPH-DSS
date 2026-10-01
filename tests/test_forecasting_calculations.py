import unittest

import numpy as np
import pandas as pd

from forecasting_calculations import (
    calculate_forecast_metrics,
    category_selection_status,
    evaluate_category_eligibility,
    exponential_smoothing,
    format_forecast_output,
    linear_regression,
    moving_average,
    seasonal_index_adjustment,
    select_best_forecast_method,
)


def history(categories: int = 2, periods: int = 6) -> pd.DataFrame:
    rows = []
    for category_number in range(categories):
        for period_number, time in enumerate(
            pd.date_range("2025-01-01", periods=periods, freq="MS"), start=1
        ):
            rows.append(
                {
                    "Time": time,
                    "Category": f"Category {category_number + 1}",
                    "Demand": float(period_number + category_number),
                    "Revenue": float((period_number + category_number) * 10),
                    "Observed": True,
                }
            )
    return pd.DataFrame(rows)


class ForecastMethodTests(unittest.TestCase):
    def test_each_forecast_method_returns_the_clean_contract(self) -> None:
        data = history(categories=1, periods=24)
        moving = moving_average(data, frequency="M", horizon=2, window=3)
        exponential = exponential_smoothing(data, frequency="M", horizon=2, alpha=0.4)
        regression = linear_regression(data, frequency="M", horizon=2)
        seasonal = seasonal_index_adjustment(
            data, moving, frequency="M", season_length=12
        )

        for output in [moving, exponential, regression, seasonal]:
            self.assertIsInstance(output, pd.DataFrame)
            self.assertEqual(output.columns.tolist(), ["Time", "Category", "Forecast", "Method"])
            self.assertEqual(len(output), 2)

        self.assertAlmostEqual(moving.iloc[0]["Forecast"], np.mean([22, 23, 24]))
        self.assertAlmostEqual(regression.iloc[0]["Forecast"], 25.0)
        self.assertEqual(seasonal.iloc[0]["Method"], "Moving Average + Seasonal Index")

    def test_metrics_match_manual_calculation(self) -> None:
        validation = pd.DataFrame(
            {
                "Category": ["A", "A", "A"],
                "Method": ["Moving Average", "Moving Average", "Moving Average"],
                "Actual": [10.0, 20.0, 30.0],
                "Forecast": [12.0, 18.0, 33.0],
            }
        )
        result = calculate_forecast_metrics(
            validation, mape_zero_actual_policy="exclude"
        ).iloc[0]

        self.assertAlmostEqual(result["MAE"], (2 + 2 + 3) / 3)
        self.assertAlmostEqual(result["RMSE"], np.sqrt((4 + 4 + 9) / 3))
        self.assertAlmostEqual(result["MAPE"], ((2 / 10) + (2 / 20) + (3 / 30)) / 3 * 100)
        self.assertAlmostEqual(result["R2"], 1 - (4 + 4 + 9) / 200)

    def test_method_selection_uses_explicit_metric_priority(self) -> None:
        metrics = pd.DataFrame(
            {
                "Category": ["A", "A"],
                "Method": ["Moving Average", "Linear Regression"],
                "MAE": [2.0, 1.0],
                "RMSE": [3.0, 3.0],
                "MAPE": [10.0, 8.0],
                "R2": [0.7, 0.8],
            }
        )
        result = select_best_forecast_method(
            metrics, primary_metric="RMSE", secondary_metric="MAE"
        )
        self.assertEqual(result.iloc[0]["Method"], "Linear Regression")


class CategoryEligibilityTests(unittest.TestCase):
    def evaluate(self, categories: int, minimum_history_periods: int = 3) -> pd.DataFrame:
        return evaluate_category_eligibility(
            history(categories=categories, periods=3),
            minimum_history_periods=minimum_history_periods,
            minimum_completeness=1.0,
            minimum_consistency=1.0,
            demand_contribution_weight=0.5,
            revenue_contribution_weight=0.5,
        )

    def test_one_eligible_category(self) -> None:
        self.assertEqual(int(self.evaluate(1)["Selected"].sum()), 1)

    def test_two_eligible_categories(self) -> None:
        self.assertEqual(int(self.evaluate(2)["Selected"].sum()), 2)

    def test_three_eligible_categories(self) -> None:
        self.assertEqual(int(self.evaluate(3)["Selected"].sum()), 3)

    def test_more_than_three_eligible_categories(self) -> None:
        result = self.evaluate(5)
        self.assertEqual(int(result["Eligible"].sum()), 5)
        self.assertEqual(int(result["Selected"].sum()), 3)

    def test_no_eligible_category_returns_insufficient_data_state(self) -> None:
        result = self.evaluate(2, minimum_history_periods=4)
        status = category_selection_status(result).iloc[0]
        self.assertEqual(int(result["Selected"].sum()), 0)
        self.assertEqual(status["Status"], "Insufficient Data")

    def test_final_output_has_only_approved_fields(self) -> None:
        forecasts = pd.DataFrame(
            {
                "Time": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "Category": ["A", "A"],
                "Forecast": [10.0, 12.0],
                "Method": ["Moving Average", "Moving Average"],
            }
        )
        metrics = pd.DataFrame(
            {
                "Category": ["A"],
                "Method": ["Moving Average"],
                "MAE": [1.0],
                "RMSE": [1.2],
                "MAPE": [5.0],
                "R2": [0.9],
            }
        )
        result = format_forecast_output(forecasts, metrics, forecast_aggregation="sum")

        self.assertEqual(
            result.columns.tolist(),
            ["Category", "Forecast", "Method", "MAE", "RMSE", "MAPE", "R2"],
        )
        self.assertEqual(result.iloc[0]["Forecast"], 22.0)


if __name__ == "__main__":
    unittest.main()
