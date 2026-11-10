from pathlib import Path

import pandas as pd
import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import utils.analytics_display as analytics_display
import utils.state as shared_state
from utils.forecast_table import sku_forecast_horizon, sku_forecast_table
from utils.risk_filters import calculate_days_of_supply, filter_risk_records
from utils.recommendation_filters import filter_recommendations, recommendation_summary_group
from utils.movement_display import movement_table_views
from utils.prioritization_display import ranking_table
from utils.session_timeout import clear_reload_script, guarded_reload_script, reload_delay_ms
from utils.state import DEFAULT_STATE, DataStatus


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_days_of_supply_handles_zero_missing_and_real_values():
    assert calculate_days_of_supply(20, 10) == 14.0
    assert calculate_days_of_supply(20, 0) == "N/A — No Forecast Demand"
    assert calculate_days_of_supply(None, 10) == "N/A"
    assert calculate_days_of_supply(20, None) == "N/A"


def test_product_movement_preview_and_view_all_share_all_filtered_rows():
    filtered = pd.DataFrame({"Product": [f"P-{i}" for i in range(15)], "Movement": ["Fast"] * 15})
    preview, full = movement_table_views(filtered)
    assert len(preview) == 12
    pd.testing.assert_frame_equal(full, filtered)


def test_product_ranking_includes_raw_mca_criteria_and_existing_score():
    source = pd.DataFrame([{
        "Priority Rank": 1, "Product": "Alpha", "SKU": "A-1",
        "Sales Velocity": 2.5, "Forecasted Demand": 17.0,
        "Recorded Return/Refund Quantity Rate": 0.125,
        "Normalized Sales Velocity": .8, "SKU Priority Score": .72,
        "Priority Level": "High",
    }])
    table = ranking_table(source, lambda _row: "Existing reason")
    assert table.loc[0, "Sales Velocity (units/day)"] == 2.5
    assert table.loc[0, "Forecast Demand (units)"] == 17.0
    assert table.loc[0, "Return Rate (recorded units)"] == .125
    assert table.loc[0, "MCA Score"] == .72
    assert "Normalized Sales Velocity" not in table.columns


def test_session_timeout_script_replaces_stale_timer_and_checks_deadline():
    first = guarded_reload_script(1000.0, reload_delay_ms(1000.0, 900.0))
    second = guarded_reload_script(1100.0, reload_delay_ms(1100.0, 1000.0))
    assert "clearTimeout" in first and "clearTimeout" in second
    assert "activeToken > token" in second
    assert "__tesphSessionTimeoutReloadToken !== token" in second
    assert "remaining <= 0" in second
    assert "host.location.reload()" in second
    assert "ReloadToken = null" in clear_reload_script()
    assert reload_delay_ms(1000.0, 1001.0) >= 250


def test_sku_forecast_table_requires_complete_seven_day_data_and_handles_missing_fields():
    base = pd.DataFrame({
        "SKU": ["S-1"] * 7 + ["S-2"],
        "Product": ["Product 1"] * 7 + ["Product 2"],
        "Time": list(pd.date_range("2026-01-01", periods=7)) + [pd.Timestamp("2026-01-01")],
        "Forecast": [1, 2, 3, 4, 5, 6, 7, 9],
        "Method": ["Moving Average"] * 8,
    })
    result = sku_forecast_table({"forecast_output": base})
    assert result["SKU"].tolist() == ["S-1"]
    assert result["7-Day Projected Units"].iloc[0] == 28
    assert result["Forecast Detail"].iloc[0].count(";") == 6
    assert sku_forecast_table({"forecast_output": base.iloc[:0]}).empty
    assert sku_forecast_table({"forecast_output": pd.DataFrame({"SKU": ["S-1"]})}).empty
    horizon = sku_forecast_horizon({"forecast_output": base}, result)
    assert horizon == (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-07"))
    assert sku_forecast_horizon({"forecast_output": base.iloc[:1]}, result) is None


def test_risk_search_and_no_forecast_filter_combine_case_insensitively():
    data = pd.DataFrame({
        "SKU": ["ABC-1", "XYZ-2", "LMN-3", "QRS-4"],
        "Product": ["Blue Mug", "Mug Blue XL", "Green Mug", "Other"],
        "Stock-Out Risk": ["No Forecast Demand", "Low", "High", "Medium"],
        "Priority Level": ["Low", "High", "Medium", "Low"],
    })
    result = filter_risk_records(data, "No Forecast Demand", "mUg")
    assert result["SKU"].tolist() == ["ABC-1"]
    assert filter_risk_records(data, "High")["SKU"].tolist() == ["XYZ-2"]
    assert filter_risk_records(data, "Medium")["SKU"].tolist() == ["LMN-3"]
    assert filter_risk_records(data, "Low")["SKU"].tolist() == ["ABC-1", "QRS-4"]
    assert filter_risk_records(data, "Low", "missing").empty
    assert filter_risk_records(pd.DataFrame({"Product": ["Product"]}), "High").empty


def test_recommendation_urgency_mapping_and_search_use_existing_values():
    data = pd.DataFrame({
        "SKU": ["A-1", "B-2", "C-3", "D-4"],
        "Product": ["Alpha", "Beta", "Gamma", "Delta"],
        "Recommendation Priority": ["Immediate", "High", "Medium", "None"],
        "Recommendation": [None, None, None, "No Immediate Restock / Monitor Demand"],
    })
    assert [recommendation_summary_group(row) for _, row in data.iterrows()] == ["Urgent", "Urgent", "Recommended", "Monitor"]
    result = filter_recommendations(data, "Urgent", "b-2")
    assert result["SKU"].tolist() == ["B-2"]
    assert filter_recommendations(data, "Monitor", "no-match").empty
    assert filter_recommendations(pd.DataFrame(), "Urgent", "x").empty


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
            "pages/demand_forecast.py": 2,
            "pages/stock_out_risk.py": 1,
        "pages/product_prioritization.py": 4,
        "pages/replenishment_recommendations.py": 1,
    }
    for page_path, table_count in expected_tables.items():
        previous_chart_count = len(charts)
        app.switch_page(page_path).run()
        assert not app.exception, page_path
        assert len(app.dataframe) >= table_count, page_path
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
