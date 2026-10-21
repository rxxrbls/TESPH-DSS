import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from forecasting_calculations import calculate_r_squared
from sku_forecasting import backtest_sku
from utils.forecast_display import accuracy_table, format_metric
from test_week2 import transactions, approved_mapping, settings
from forecasting_pipeline import run_forecasting_pipeline


@pytest.mark.parametrize("value,expected", [(None, "N/A"), (np.nan, "N/A"), (np.inf, "N/A"), ("invalid", "N/A"), (0, "0.00"), (0.000001, "1.0000e-06"), (-0.000001, "-1.0000e-06"), (-2, "-2.0000")])
def test_missing_zero_and_small_values_are_distinct(value, expected):
    assert format_metric(value) == expected


def test_r_squared_is_scale_invariant_and_constant_actuals_are_undefined():
    detail = pd.DataFrame({"Category": ["A"] * 3, "Method": ["Linear Regression"] * 3,
                           "Actual": [1e-6, 2e-6, 3e-6], "Forecast": [1e-6, 2e-6, 3e-6]})
    assert calculate_r_squared(detail).R2.iloc[0] == 1
    assert np.isnan(calculate_r_squared(detail.assign(Actual=0)).R2.iloc[0])
    assert np.isnan(calculate_r_squared(detail.assign(Actual=0.1)).R2.iloc[0])


def test_backtest_rejects_calendar_misalignment():
    data = pd.DataFrame({"Time": pd.date_range("2026-01-01", periods=20), "Demand": 1.,
                         "SKU": "S", "Product": "P", "Category": "C"})
    data.loc[19, "Time"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="dates"):
        backtest_sku(data, settings())


def test_constant_actual_reason_and_real_page_binding():
    from pathlib import Path
    from utils.state import DEFAULT_STATE, DataStatus
    data = transactions().assign(Quantity=0, **{"Total Buyer Payment": 0})
    results = run_forecasting_pipeline(data, mapping=approved_mapping(data), config=settings())
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "pages/demand_forecast.py")
    state = {**DEFAULT_STATE, "authenticated": True, "data_status": DataStatus.DATA_READY.value,
             "prepared_transactions": data, "active_dataset_id": "test", "forecast_dataset_id": "test",
             "forecast_results": results, "_runtime_authority_loaded": True}
    for key, value in state.items():
        app.session_state[key] = value
    app.run(timeout=30)
    assert not app.exception
    table = next(item.value for item in app.dataframe if "R² Status" in item.value)
    pd.testing.assert_frame_equal(table, accuracy_table(results["validation_metrics"], results["best_methods"], results["validation_detail"]))
    assert table["R² Status"].eq("N/A: constant actual demand").all()
    assert table["MAE"].eq("0.00").all()
    assert table["Raw MAPE (%)"].eq("N/A").all()
    assert table.Selection.eq("Selected").sum() == 2


def test_empty_results_show_no_fabricated_metrics():
    app = AppTest.from_string("from utils.forecast_display import render_forecast_accuracy\nrender_forecast_accuracy({})").run()
    assert not app.exception
    assert not app.dataframe
    assert "unavailable" in app.info[0].value
