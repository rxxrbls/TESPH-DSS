from pathlib import Path

import pandas as pd
import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import utils.analytics_display as analytics_display
import utils.state as shared_state
from utils.state import DEFAULT_STATE, DataStatus


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _populated_session() -> dict:
    dataset_id = "ui-test-dataset"
    return {
        **DEFAULT_STATE,
        "authenticated": True,
        "data_status": DataStatus.DATA_READY.value,
        "prepared_transactions": pd.DataFrame({"Order ID": ["O-1"]}),
        "active_dataset_id": dataset_id,
        "_runtime_authority_loaded": True,
        "_bootstrapped": True,
        "star_schema": {"dim_product": pd.DataFrame({"product_key": ["P-1"]})},
        "analytics_results": {
            "sales_summary": pd.DataFrame([{
                "Gross Revenue": 100.0,
                "Net Revenue After Returns": 90.0,
                "Gross Demand": 5,
                "Return Quantity Rate": 0.2,
                "Cancellation Order Rate": 0.0,
                "Order Count": 2,
                "Product Count": 1,
                "Average Order Value": 50.0,
                "Returned Quantity": 1,
                "Return Order Rate": 0.5,
            }]),
            "sales_trends": pd.DataFrame([{
                "Time": pd.Timestamp("2026-01-01"),
                "Category": "A",
                "Net Revenue After Returns": 90.0,
                "Gross Demand": 5,
            }]),
            "product_performance": pd.DataFrame([{
                "Product Key": "P-1",
                "SKU": "S-1",
                "Product": "Product 1",
                "Category": "A",
                "Gross Revenue": 100.0,
                "Net Inventory Demand": 5,
                "Returned Quantity": 1,
                "Return Quantity Rate": 0.2,
            }]),
            "return_indicators": pd.DataFrame([{
                "Returned Quantity": 1,
                "Return Order Rate": 0.5,
            }]),
            "return_indicators_by_category": pd.DataFrame([{
                "Category": "A",
                "Returned Quantity": 1,
            }]),
            "order_status": pd.DataFrame([{
                "Order Status": "Cancelled",
                "Order Count": 1,
                "Quantity": 1,
            }]),
            "movement_classified": pd.DataFrame([{
                "Product": "Product 1",
                "Movement Classification": "Stable",
            }]),
            "sales_velocity": pd.DataFrame([{"SKU": "S-1", "Velocity": 1.0}]),
        },
        "analytics_dataset_id": dataset_id,
        "forecast_results": {
            "category_eligibility": pd.DataFrame([{
                "Category": "A",
                "Eligible": True,
                "Eligibility Rank": 1,
                "Selected": True,
                "Demand Contribution": 1.0,
                "Revenue Contribution": 1.0,
                "Contribution": 1.0,
            }]),
            "category_validation_detail": pd.DataFrame([
                {
                    "Category": "A",
                    "Time": pd.Timestamp("2026-01-01"),
                    "Method": "Moving Average",
                    "Actual": 5.0,
                    "Forecast": 4.0,
                },
                {
                    "Category": "A",
                    "Time": pd.Timestamp("2026-01-02"),
                    "Method": "Moving Average",
                    "Actual": 6.0,
                    "Forecast": 5.0,
                },
            ]),
            "selection_status": pd.DataFrame([{
                "Status": "Ready",
                "Forecast SKU Count": 1,
            }]),
            "forecast_output": pd.DataFrame([{
                "SKU": "S-1",
                "Product": "Product 1",
                "Category": "A",
                "Time": pd.Timestamp("2026-02-01"),
                "Forecast": 4.0,
                "Method": "Moving Average",
            }]),
            "product_forecast": pd.DataFrame([{
                "Product": "Product 1",
                "Category": "A",
                "Time": pd.Timestamp("2026-02-01"),
                "Forecast": 4.0,
            }]),
            "category_forecast": pd.DataFrame([{
                "Category": "A",
                "Time": pd.Timestamp("2026-02-01"),
                "Forecast": 4.0,
            }]),
            "validation_metrics": pd.DataFrame([{
                "SKU": "S-1",
                "Category": "A",
                "Method": "Moving Average",
                "MAE": 1.0,
                "RMSE": 1.0,
                "MAPE": 10.0,
                "R2": 0.9,
            }]),
            "best_methods": pd.DataFrame([{
                "SKU": "S-1",
                "Category": "A",
                "Method": "Moving Average",
            }]),
            "parameter_search": pd.DataFrame([{"SKU": "S-1", "Method": "MA"}]),
            "eligibility": pd.DataFrame([{"SKU": "S-1", "Eligible": True}]),
        },
        "forecast_dataset_id": dataset_id,
        "inventory_data": pd.DataFrame([{"SKU": "S-1", "Stock": 10}]),
        "inventory_crosswalk": pd.DataFrame([{
            "product_key": "P-1",
            "SKU": "S-1",
            "Stock": 10,
            "match_status": "candidate",
            "mapping_review_required": False,
        }]),
        "inventory_validation": {"valid": True},
        "risk_results": pd.DataFrame([{
            "SKU": "S-1",
            "Product": "Product 1",
            "Current Stock": 10,
            "Forecast Demand": 4.0,
            "Stock-Out Risk": "Low",
        }]),
        "mca_results": pd.DataFrame([{"SKU": "S-1", "SKU Priority Score": 0.8}]),
        "recommendation_results": pd.DataFrame([{
            "SKU": "S-1",
            "Product": "Product 1",
            "Category": "A",
            "Recommended Quantity": 2,
        }]),
    }


def test_authenticated_router_renders_populated_downstream_page_inputs(monkeypatch):
    charts = []
    monkeypatch.setattr(
        analytics_display.st,
        "vega_lite_chart",
        lambda frame, spec, **_kwargs: charts.append((frame.copy(), spec)),
    )
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    for key, value in _populated_session().items():
        app.session_state[key] = value

    app.run()
    dashboard_kpis = " ".join(
        str(element.value) for element in app.markdown
        if 'class="kpi-value"' in str(element.value)
    )
    assert not app.exception
    assert "₱100.00" in dashboard_kpis
    assert len(charts) == 3
    category_mix_spec = charts[1][1]
    assert category_mix_spec["mark"]["type"] == "arc"
    assert category_mix_spec["mark"]["innerRadius"] > 0

    def assert_charts_are_bound_to_dataframes(start: int, expected: int) -> None:
        new_charts = charts[start:]
        assert len(new_charts) == expected
        for frame, spec in new_charts:
            encoding = spec["encoding"]
            fields = {
                encoding[channel]["field"]
                for channel in ("x", "y", "theta", "color")
                if channel in encoding
            } | {
                tooltip["field"] for tooltip in encoding.get("tooltip", [])
            }
            mark = spec["mark"]
            assert not frame.empty
            assert fields.issubset(frame.columns)
            assert spec.get("height", 0) > 0
            assert mark.get("opacity", 1) > 0

    assert_charts_are_bound_to_dataframes(0, 3)

    expected_tables = {
        "pages/sales_product_analytics.py": 0,
            "pages/demand_forecast.py": 1,
            "pages/stock_out_risk.py": 1,
        "pages/product_prioritization.py": 4,
        "pages/replenishment_recommendations.py": 1,
    }
    for page_path, table_count in expected_tables.items():
        previous_chart_count = len(charts)
        app.switch_page(page_path).run()
        assert not app.exception, page_path
        assert len(app.dataframe) == table_count, page_path
        assert all(not element.value.empty for element in app.dataframe), page_path
        assert app.session_state["active_dataset_id"] == app.session_state["analytics_dataset_id"]
        assert app.session_state["active_dataset_id"] == app.session_state["forecast_dataset_id"]
        expected_new_charts = {
            "pages/sales_product_analytics.py": 2,
            "pages/demand_forecast.py": 1,
            "pages/stock_out_risk.py": 2,
        }.get(page_path, 0)
        assert_charts_are_bound_to_dataframes(previous_chart_count, expected_new_charts)


def test_demand_forecast_page_auto_generates_missing_forecast(monkeypatch):
    generation_calls = []

    def fake_ensure_outputs():
        generation_calls.append(True)
        shared_state.st.session_state["forecast_results"] = {
            "category_eligibility": pd.DataFrame([
                {
                    "Category": "Kitchenware",
                    "Eligible": True,
                    "Eligibility Rank": 1,
                    "Selected": True,
                    "Demand Contribution": 0.4,
                    "Revenue Contribution": 0.3,
                    "Contribution": 0.35,
                }
            ]),
            "sku_dataset": pd.DataFrame([
                {
                    "SKU": "S-1",
                    "Product": "Product 1",
                    "Category": "Kitchenware",
                    "Time": pd.Timestamp("2026-04-01"),
                    "Demand": 10,
                    "Revenue": 100,
                    "Observed": True,
                }
            ]),
            "category_validation_detail": pd.DataFrame([
                {
                    "Category": "Kitchenware",
                    "Time": pd.Timestamp("2026-04-02"),
                    "Method": "Moving Average",
                    "Actual": 10,
                    "Forecast": 9,
                },
                {
                    "Category": "Kitchenware",
                    "Time": pd.Timestamp("2026-04-02"),
                    "Method": "Exponential Smoothing",
                    "Actual": 10,
                    "Forecast": 8,
                },
                {
                    "Category": "Kitchenware",
                    "Time": pd.Timestamp("2026-04-02"),
                    "Method": "Linear Regression",
                    "Actual": 10,
                    "Forecast": 11,
                },
            ]),
            "forecast_output": pd.DataFrame(columns=[
                "SKU",
                "Product",
                "Category",
                "Time",
                "Forecast",
                "Method",
            ]),
            "validation_metrics": pd.DataFrame([
                {
                    "SKU": "S-1",
                    "Product": "Product 1",
                    "Category": "Kitchenware",
                    "Method": "Moving Average",
                    "MAE": 1,
                    "RMSE": 1,
                    "MAPE": 10,
                    "R2": 0.9,
                    "MAPE Status": "Defined",
                }
            ]),
            "best_methods": pd.DataFrame([
                {
                    "SKU": "S-1",
                    "Method": "Moving Average",
                }
            ]),
            "selection_status": pd.DataFrame([{
                "Status": "Ready",
                "Forecast SKU Count": 1,
            }]),
        }
        shared_state.st.session_state["forecast_dataset_id"] = shared_state.st.session_state["active_dataset_id"]

    monkeypatch.setattr(shared_state, "ensure_derived_outputs_for_active_dataset", fake_ensure_outputs)
    forecast_page = APP_PATH.parent / "pages" / "demand_forecast.py"
    app = AppTest.from_file(str(forecast_page), default_timeout=30)
    app.session_state["authenticated"] = True
    app.session_state["data_status"] = DataStatus.DATA_READY.value
    app.session_state["prepared_transactions"] = pd.DataFrame({"Order ID": ["O-1"]})
    app.session_state["active_dataset_id"] = "ui-test-dataset"
    app.session_state["_runtime_authority_loaded"] = True
    app.run()

    assert not app.exception
    assert generation_calls == [True]
    assert all(button.label != "Prepare demand forecast" for button in app.button)
    assert not any(
        "Forecast chart data is unavailable" in str(element.value)
        for element in app.markdown
    )

    app.run()
    assert not app.exception
    assert generation_calls == [True]
