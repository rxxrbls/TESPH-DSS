"""Independent arithmetic and temporal-contract checks for Week 2."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from analytics_calculations import (
    calculate_cancellation_indicators, calculate_sales_trends,
    calculate_yoy_revenue_growth, exclude_incomplete_latest_month,
)
from analytics_data import load_transactions
from analytics_pipeline import run_analytics_pipeline
from forecasting_calculations import calculate_forecast_metrics
from forecasting_pipeline import run_forecasting_pipeline
from methodology_config import ForecastConfig
from sku_forecasting import mapping_template, prepare_sku_history, validate_mapping


def transactions():
    rows = []
    for sku, multiplier in (("001", 1), ("002", 2)):
        for i, day in enumerate(pd.date_range("2026-01-01", periods=20)):
            quantity = (i % 5) * multiplier
            rows.append({"Order ID": f"{sku}-{i}", "Order Status": "Completed",
                         "SKU Reference No.": sku, "Product Name": "Source Product",
                         "product_key": "key-" + sku, "final_base_product_name": "Product",
                         "final_category": "Category", "order_date": day,
                         "Quantity": quantity, "Returned quantity": 0, "Deal Price": 10,
                         "Total Buyer Payment": quantity * 10, "is_completed": True,
                         "is_cancelled": False, "is_returned": False})
    return pd.DataFrame(rows)


def approved_mapping(data):
    return mapping_template(data).assign(active=True, category_active=True, client_approved=True)


def settings(**kwargs):
    return replace(ForecastConfig(frequency="D", horizon=1, validation_periods=3, tuning_periods=3,
                                  minimum_training_periods=6, ma_windows=(2, 3),
                                  es_alphas=(0.1, 0.5, 0.9)), **kwargs)


def test_forecasts_stay_at_sku_grain_and_aggregate_bottom_up():
    data = transactions()
    result = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=settings(horizon=2))
    output = result["forecast_output"]
    assert set(output["SKU"]) == {"001", "002"}
    assert len(output) == 4
    assert output["Time"].min() == pd.Timestamp("2026-01-21")
    assert output["Forecast"].ge(0).all()
    for name in ("product_forecast", "category_forecast"):
        expected = output.groupby("Time")["Forecast"].sum()
        pd.testing.assert_series_equal(result[name].set_index("Time")["Forecast"], expected)
    detail = result["validation_detail"]
    assert detail.groupby(["SKU", "Method"]).size().eq(6).all()
    assert (detail["Origin"] < detail["Time"]).all()


def test_nested_tuning_cannot_see_the_current_or_future_holdout():
    data = transactions()
    mapping = approved_mapping(data)
    before = run_forecasting_pipeline(data, mapping=mapping, config=settings())["validation_detail"]
    data.loc[data["order_date"].eq(pd.Timestamp("2026-01-19")), "Quantity"] = 10000
    after = run_forecasting_pipeline(data, mapping=mapping, config=settings())["validation_detail"]
    cols = ["SKU", "Origin", "Time", "Method", "Forecast", "MA Window", "ES Alpha"]
    pd.testing.assert_frame_equal(before.loc[before.Time.le("2026-01-19"), cols],
                                  after.loc[after.Time.le("2026-01-19"), cols])


def test_no_mapping_means_no_operational_forecasts():
    result = run_forecasting_pipeline(transactions(), config=settings())
    assert result["forecast_output"].empty
    assert not result["eligibility"]["Eligible"].any()
    assert result["selection_status"].iloc[0]["Methodology Status"].startswith("TA constraints")


@pytest.mark.parametrize("column,reason", [("active", "Inactive SKU"),
                                           ("category_active", "Inactive category"),
                                           ("client_approved", "Not client-approved")])
def test_inactive_and_unapproved_items_are_excluded(column, reason):
    data = transactions()
    mapping = approved_mapping(data)
    mapping[column] = False
    result = run_forecasting_pipeline(data, mapping=mapping, config=settings())
    assert result["forecast_output"].empty
    assert result["eligibility"]["Reason"].eq(reason).all()


def test_missing_source_sku_can_only_be_resolved_by_explicit_mapping():
    data = transactions()
    mapping = approved_mapping(data)
    data["SKU Reference No."] = pd.NA
    assert mapping_template(data)["SKU"].isna().all()
    result = run_forecasting_pipeline(data, mapping=mapping, config=settings())
    assert set(result["forecast_output"]["SKU"]) == {"001", "002"}
    assert data["SKU Reference No."].isna().all()


def test_multiple_historical_keys_map_to_one_sku_without_double_counting():
    data = transactions()
    mapping = approved_mapping(data)
    mapping["SKU"] = "CURRENT-SKU"
    result = run_forecasting_pipeline(data, mapping=mapping, config=settings())
    assert result["forecast_output"]["SKU"].nunique() == 1
    assert result["sku_dataset"]["Demand"].sum() == data["Quantity"].sum()


def test_mapping_rejects_duplicates_conflicts_and_unknown_flags():
    mapping = approved_mapping(transactions())
    with pytest.raises(ValueError, match="one row"):
        validate_mapping(pd.concat([mapping, mapping]))
    with pytest.raises(ValueError, match="consistent"):
        validate_mapping(mapping.assign(SKU="same", Product=["A", "B"]))
    with pytest.raises(ValueError, match="true/false"):
        validate_mapping(mapping.assign(active="maybe"))
    with pytest.raises(ValueError, match="require SKU"):
        validate_mapping(mapping.assign(SKU=pd.NA))


def test_calendar_fills_zero_days_through_coverage_without_prelaunch_history():
    data = transactions().iloc[:3].copy()
    data = data.iloc[[0, 2]]
    history = prepare_sku_history(data, settings(), coverage_end="2026-01-05")
    assert history["Demand"].tolist() == [0, 0, 2, 0, 0]
    assert history["Observed"].tolist() == [True, False, True, False, False]
    assert history.Time.min() == pd.Timestamp("2026-01-01")


def test_short_history_and_empty_data_have_stable_outputs():
    for data in (transactions().iloc[:2], transactions().iloc[:0]):
        result = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=settings())
        assert result["forecast_output"].empty
        assert "Method" in result["validation_detail"]
        assert "SKU" in result["best_methods"]


def test_new_products_without_complete_months_are_in_exclusion_report():
    data = transactions().iloc[:2]
    result = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=ForecastConfig(frequency="M", horizon=1))
    assert result["forecast_output"].empty
    assert len(result["eligibility"]) == 1
    assert result["eligibility"].iloc[0]["Reason"] == "No complete history"


def test_metrics_match_manual_values_and_keep_zero_actuals():
    detail = pd.DataFrame({"Category": ["A"] * 3, "Method": ["MA"] * 3,
                           "Actual": [0.0, 2.0, 4.0], "Forecast": [1.0, 1.0, 3.0]})
    result = calculate_forecast_metrics(detail, mape_zero_actual_policy="return_nan").iloc[0]
    assert result.MAE == 1
    assert result.RMSE == 1
    assert result.R2 == 1 - 3 / 8
    assert np.isnan(result.MAPE)
    adjusted = calculate_forecast_metrics(detail, mape_zero_actual_policy="denominator_floor",
                                          mape_denominator_floor=1).iloc[0]
    assert adjusted.MAPE == pytest.approx((1 + 0.5 + 0.25) / 3 * 100)


def test_ties_are_deterministic_and_parameter_search_is_recorded():
    data = transactions().assign(Quantity=10)
    result = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=settings())
    # Alphabetical final tie-break matches the existing deterministic selector.
    assert result["best_methods"]["Method"].eq("Exponential Smoothing").all()
    search = result["parameter_search"]
    assert set(search["MA Window"].dropna()) == {2, 3}
    assert set(search["ES Alpha"].dropna()) == {0.1, 0.5, 0.9}
    assert search["Tuning Observations"].eq(3).all()


def test_leading_zero_identifiers_survive_csv_loading(tmp_path):
    path = tmp_path / "prepared_transactions.csv"
    transactions().to_csv(path, index=False)
    assert set(load_transactions(path)["SKU Reference No."]) == {"001", "002"}


def test_daily_windows_and_no_zero_exclusion_configuration():
    assert ForecastConfig(frequency="D").windows == (3, 7, 14, 30)
    with pytest.raises(ValueError, match="retain"):
        settings(mape_zero_policy="exclude").validate()
    with pytest.raises(ValueError, match="floor"):
        settings(mape_zero_policy="denominator_floor", mape_denominator_floor=None).validate()


def test_category_filter_does_not_make_covered_month_incomplete():
    data = transactions().iloc[:2].copy()
    data["order_date"] = ["2026-01-15", "2026-02-03"]
    result = exclude_incomplete_latest_month(data, coverage_end="2026-03-24")
    assert len(result) == 2


def test_filtered_stale_products_use_global_coverage_for_movement():
    data = transactions().iloc[:2].copy()
    data["order_date"] = ["2025-10-31", "2025-11-30"]
    data["Quantity"] = 10
    result = run_analytics_pipeline(data, coverage_end="2026-03-31")
    assert result["movement_classified"].iloc[0]["Movement Classification"] == "No Movement"
    assert result["sales_velocity"].iloc[0]["Sales Velocity"] == 0


def test_yoy_requires_the_immediately_previous_calendar_year():
    data = transactions().iloc[:2].copy()
    data["order_date"] = ["2024-01-31", "2026-01-31"]
    data["Total Buyer Payment"] = [100, 200]
    result = calculate_yoy_revenue_growth(data, through_month=1)
    assert result.iloc[-1]["Comparable Revenue"] == 200
    assert np.isnan(result.iloc[-1]["YoY Revenue Growth"])


def test_descriptive_views_match_manual_transaction_arithmetic():
    data = transactions().iloc[:4].copy()
    data["order_date"] = ["2025-12-31", "2026-01-31", "2026-02-28", "2026-03-31"]
    data["Quantity"] = [2, 3, 4, 5]
    data["Total Buyer Payment"] = [20, 30, 40, 50]
    data["is_completed"] = [True, False, True, True]
    data["is_cancelled"] = [False, True, False, False]
    data["Order Status"] = ["Completed", "Cancelled", "Completed", "Completed"]
    data["Returned quantity"] = [0, 0, 1, 0]
    data["is_returned"] = [False, False, True, False]
    data["Cancel reason"] = [None, "Changed mind", None, None]
    result = run_analytics_pipeline(data)
    summary = result["sales_summary"].iloc[0]
    assert summary["Gross Revenue"] == 110
    assert summary["Gross Demand"] == 11
    assert summary["Net Inventory Demand"] == 10
    assert summary["Average Order Value"] == pytest.approx(110 / 3)
    assert summary["Cancellation Order Rate"] == 0.25
    assert result["return_indicators"].iloc[0]["Return Quantity Rate"] == pytest.approx(1 / 11)
    assert result["product_performance"].iloc[0]["Gross Revenue"] == 110
    assert calculate_sales_trends(data, frequency="M")["Gross Revenue"].tolist() == [20, 0, 40, 50]
    cancellation = calculate_cancellation_indicators(data).iloc[0]
    assert cancellation["Cancelled Order Count"] == 1
    assert cancellation["Cancelled Quantity"] == 3
    assert cancellation["Cancel Reason"] == "Changed mind"
    movement = result["movement_classified"].iloc[0]
    assert movement["Recent Demand"] == 9
    assert movement["Movement Classification"] == "Regular Moving"
    assert result["sales_velocity"].iloc[0]["Sales Velocity"] == 3
