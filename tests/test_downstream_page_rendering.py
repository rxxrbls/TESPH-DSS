from pathlib import Path

import pandas as pd
import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import utils.analytics_display as analytics_display
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
            "validation_metrics": pd.DataFrame([{"SKU": "S-1", "RMSE": 1.0}]),
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
        "risk_results": pd.DataFrame([{"SKU": "S-1", "Stock-Out Risk": "Low"}]),
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

    def assert_charts_are_bound_to_dataframes(start: int, expected: int) -> None:
        new_charts = charts[start:]
        assert len(new_charts) == expected
        for frame, spec in new_charts:
            encoding = spec["encoding"]
            fields = {
                encoding[axis]["field"] for axis in ("x", "y")
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
        "pages/sales_product_analytics.py": 5,
        "pages/demand_forecast.py": 7,
        "pages/stock_out_risk.py": 2,
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
            "pages/stock_out_risk.py": 1,
        }.get(page_path, 0)
        assert_charts_are_bound_to_dataframes(previous_chart_count, expected_new_charts)