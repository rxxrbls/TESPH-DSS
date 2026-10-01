"""TA constraints, team decisions, and independent edge-case expectations."""

import numpy as np
import pandas as pd
import pytest

from active_inventory import build_active_mapping
from analytics_calculations import calculate_product_performance, calculate_return_indicators, prepare_transactions
from forecasting_calculations import calculate_forecast_metrics, select_best_forecast_method
from forecasting_pipeline import run_forecasting_pipeline
from methodology_config import ForecastConfig
from sku_forecasting import tune_parameters
from test_week2 import approved_mapping, settings, transactions


def scores(mape=(10.0, 20.0), rmse=(9.0, 1.0)):
    return pd.DataFrame({"SKU": ["001", "001"], "Category": ["A", "A"],
                         "Method": ["A", "B"], "MAPE": mape, "RMSE": rmse})


def choose(frame):
    return select_best_forecast_method(frame, primary_metric="MAPE", secondary_metric="RMSE").iloc[0]


def test_mape_first_rmse_second_and_deterministic_final_tie():
    assert choose(scores()).Method == "A"
    assert choose(scores(mape=(10, 10))).Method == "B"
    assert choose(scores(mape=(10, 10), rmse=(1, 1)).iloc[::-1]).Method == "A"


def test_undefined_mape_falls_back_only_when_all_candidates_undefined():
    winner = choose(scores(mape=(np.nan, np.nan)))
    assert winner.Method == "B"
    assert "fallback" in winner["Selection Basis"]
    with pytest.raises(ValueError, match="coverage"):
        choose(scores(mape=(np.nan, 20)))


@pytest.mark.parametrize("frame", [scores(mape=(np.inf, np.inf)), scores(rmse=(np.nan, 1)), scores(mape=(-1, 2))])
def test_selection_rejects_invalid_scores(frame):
    with pytest.raises(ValueError):
        choose(frame)


def test_all_zero_demand_is_retained_in_metrics_and_forecasts():
    data = transactions().assign(Quantity=0, **{"Total Buyer Payment": 0})
    result = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=settings())
    assert result["forecast_output"]["Forecast"].eq(0).all()
    metrics = result["validation_metrics"]
    assert metrics["MAPE"].eq(0).all()
    assert metrics["Raw MAPE"].isna().all()
    assert metrics["R2"].isna().all()
    assert metrics["Zero Actual Count"].eq(metrics["Validation Observations"]).all()
    raw = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=settings(mape_zero_policy="return_nan"))
    assert raw["best_methods"]["Selection Basis"].str.contains("fallback").all()


def test_zero_actual_overforecast_penalty_is_not_discarded():
    detail = pd.DataFrame({"Category": ["A", "A"], "Method": ["MA", "MA"],
                           "Actual": [0, 2], "Forecast": [4, 2]})
    row = calculate_forecast_metrics(detail, mape_zero_actual_policy="denominator_floor", mape_denominator_floor=1).iloc[0]
    assert row.MAPE == 200
    assert row.MAE == 2
    assert row.RMSE == pytest.approx(np.sqrt(8))


def test_default_windows_share_inner_dates_and_es_minimizes_squared_error():
    values = np.array([0, 1, 0, 3, 9, 0, 20, 2, 0, 4] * 6, dtype=float)
    train = pd.DataFrame({"Time": pd.date_range("2026-01-01", periods=len(values)), "Demand": values})
    config = ForecastConfig()
    window, alpha, search = tune_parameters(train, config)
    assert set(search["MA Window"].dropna()) == {3, 7, 14, 30}
    assert search["Tuning Observations"].eq(49).all()
    assert search["Tuning Horizon"].eq(7).all()
    expected = {}
    for candidate in config.es_alphas:
        errors = []
        for origin in range(47, 54):
            level = values[0]
            for actual in values[1:origin]:
                level = candidate * actual + (1 - candidate) * level
            errors.extend(values[origin:origin + 7] - level)
        expected[candidate] = np.sum(np.square(errors))
    assert alpha == min(expected, key=expected.get)
    ma = search.loc[search.Method.eq("Moving Average")].sort_values(["MAPE", "RMSE", "MA Window"])
    assert window == ma.iloc[0]["MA Window"]


def catalog():
    return pd.DataFrame({"product_key": ["key-001", "key-002"], "SKU": ["001", "002"],
                         "Stock As-Of Date": ["2026-09-09"] * 2, "Current Stock": [0, 10]})


def test_current_catalog_is_activity_evidence_not_fabricated_client_approval():
    mapping, review = build_active_mapping(transactions(), catalog(), as_of="2026-09-26")
    assert mapping.catalog_active.all()
    assert not mapping.client_approved.any()
    assert set(mapping.SKU) == {"001", "002"}
    assert review.Reason.eq("Eligible current catalog match").all()
    result = run_forecasting_pipeline(transactions(), mapping=mapping, config=settings())
    assert result["forecast_output"].SKU.nunique() == 2


@pytest.mark.parametrize("column,values,reason", [
    ("SKU", [None, None], "Missing source SKU"),
    ("SKU", ["same", "same"], "Reused SKU"),
    ("SKU", ["other1", "other2"], "Historical/current SKU conflict"),
    ("Stock As-Of Date", ["2020-01-01"] * 2, "stale"),
    ("Stock As-Of Date", ["2027-01-01"] * 2, "future"),
    ("Current Stock", [np.inf, -1], "Invalid current stock"),
    ("product_key", ["unknown1", "unknown2"], "No exact historical match"),
    ("active", [False, False], "Inactive catalog"),
    ("category_active", [False, False], "Inactive catalog"),
])
def test_catalog_exclusions(column, values, reason):
    inventory = catalog()
    inventory[column] = values
    mapping, review = build_active_mapping(transactions(), inventory, as_of="2026-09-26")
    assert not mapping.catalog_active.any()
    assert review.Reason.str.contains(reason).all()


@pytest.mark.parametrize("column,value", [("Quantity", np.inf), ("Total Buyer Payment", np.inf),
                                          ("Returned quantity", "bad"), ("Returned quantity", -1),
                                          ("order_date", "bad"), ("is_completed", "maybe")])
def test_bad_descriptive_inputs_raise_instead_of_silently_changing_totals(column, value):
    data = transactions().astype({column: "object"})
    data.loc[0, column] = value
    with pytest.raises(ValueError):
        prepare_transactions(data)


def test_product_return_line_denominator_matches_return_view():
    data = transactions().iloc[:3].copy()
    data["is_completed"] = [True, True, False]
    data["is_cancelled"] = [False, False, True]
    data["Returned quantity"] = [0, 1, 0]
    product = calculate_product_performance(data).iloc[0]
    overall = calculate_return_indicators(data).iloc[0]
    assert product["Demand Line Count"] == 2
    assert product["Returned-Quantity Line Rate"] == overall["Returned-Quantity Line Rate"] == 0.5
