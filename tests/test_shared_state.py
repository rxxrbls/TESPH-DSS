import pandas as pd

import utils.analytics_display as analytics_display
import utils.state as state


def test_new_dataset_clears_stock_dependent_state(monkeypatch):
    values = {
        "inventory_data": pd.DataFrame({"stock": [4]}),
        "inventory_crosswalk": pd.DataFrame({"product_key": ["old"]}),
        "inventory_validation": {"valid": True},
        "risk_results": pd.DataFrame({"Stock-Out Risk": ["High"]}),
        "mca_results": pd.DataFrame({"SKU Priority Score": [0.8]}),
        "recommendation_results": pd.DataFrame({"Recommended Quantity": [4]}),
        "forecast_results": {"forecast_output": pd.DataFrame({"SKU": ["SKU-1"]})},
        "forecast_error_message": None,
        "prescriptive_error_message": None,
        "stock_upload_feedback": None,
    }
    monkeypatch.setattr(state.st, "session_state", values)

    state.clear_stock_dependent_results()

    assert values == {
        "inventory_data": None,
        "inventory_crosswalk": None,
        "inventory_validation": None,
        "risk_results": None,
        "mca_results": None,
        "recommendation_results": None,
        "forecast_results": None,
        "forecast_dataset_id": None,
        "forecast_error_message": None,
        "prescriptive_error_message": None,
        "stock_upload_feedback": None,
    }


def test_risk_summary_accepts_existing_stock_risk_output(monkeypatch):
    rendered = []
    monkeypatch.setattr(
        analytics_display.st,
        "vega_lite_chart",
        lambda frame, _chart, **_kwargs: rendered.append(frame),
    )

    result = analytics_display.render_risk_summary(
        pd.DataFrame({"Stock-Out Risk": ["High", "Low", "High"]})
    )

    assert result is True
    assert rendered[0].to_dict("records") == [
        {"Risk level": "High", "Products": 2},
        {"Risk level": "Low", "Products": 1},
    ]


def test_dataset_mismatch_rebuilds_analytics_and_forecast_state(monkeypatch):
    values = {
        "active_dataset_id": "dataset-a",
        "analytics_results": {"sales_summary": pd.DataFrame({"Gross Revenue": [123.45]})},
        "analytics_dataset_id": "dataset-b",
        "forecast_results": {"forecast_output": pd.DataFrame({"SKU": ["SKU-1"]})},
        "forecast_dataset_id": "dataset-b",
    }
    monkeypatch.setattr(state.st, "session_state", values)

    assert state.has_valid_analytics_for_active_dataset() is False
    assert state.has_valid_forecast_for_active_dataset() is False


def test_forecast_result_with_chart_contract_is_valid_for_active_dataset(monkeypatch):
    values = {
        "active_dataset_id": "dataset-a",
        "forecast_results": {
            "forecast_output": pd.DataFrame(columns=["SKU", "Forecast"]),
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
            "category_validation_detail": pd.DataFrame([
                {
                    "Category": "Kitchenware",
                    "Time": pd.Timestamp("2026-04-01"),
                    "Method": "Moving Average",
                    "Actual": 10,
                    "Forecast": 9,
                }
            ]),
            "selection_status": pd.DataFrame([
                {"Status": "No eligible SKU forecasts", "Forecast SKU Count": 0}
            ]),
        },
        "forecast_dataset_id": "dataset-a",
    }
    monkeypatch.setattr(state.st, "session_state", values)

    assert state.has_valid_forecast_for_active_dataset() is True


def test_forecast_result_missing_category_eligibility_is_stale(monkeypatch):
    values = {
        "active_dataset_id": "dataset-a",
        "forecast_results": {
            "forecast_output": pd.DataFrame({"SKU": ["SKU-1"]}),
            "selection_status": pd.DataFrame([
                {"Status": "Ready", "Forecast SKU Count": 1}
            ]),
        },
        "forecast_dataset_id": "dataset-a",
    }
    monkeypatch.setattr(state.st, "session_state", values)

    assert state.has_valid_forecast_for_active_dataset() is False


def test_forecast_result_missing_category_chart_data_is_stale(monkeypatch):
    values = {
        "active_dataset_id": "dataset-a",
        "forecast_results": {
            "forecast_output": pd.DataFrame({"SKU": ["SKU-1"]}),
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
            "selection_status": pd.DataFrame([
                {"Status": "Ready", "Forecast SKU Count": 1}
            ]),
        },
        "forecast_dataset_id": "dataset-a",
    }
    monkeypatch.setattr(state.st, "session_state", values)

    assert state.has_valid_forecast_for_active_dataset() is False


def test_stale_forecast_regeneration_uses_default_inventory_mapping(monkeypatch):
    dataset_id = "dataset-a"
    values = {
        "active_dataset_id": dataset_id,
        "prepared_transactions": pd.DataFrame({"Order ID": ["O-1"]}),
        "analytics_results": {"sales_summary": pd.DataFrame({"Gross Revenue": [1.0]})},
        "analytics_dataset_id": dataset_id,
        "risk_results": pd.DataFrame({"SKU": ["S-1"], "Stock-Out Risk": ["Low"]}),
        "mca_results": pd.DataFrame({"SKU": ["S-1"], "SKU Priority Score": [0.8]}),
        "recommendation_results": pd.DataFrame({"SKU": ["S-1"], "Recommended Quantity": [1]}),
        "prescriptive_dataset_id": dataset_id,
        "forecast_results": {
            "forecast_output": pd.DataFrame({"SKU": ["S-1"]}),
            "selection_status": pd.DataFrame([
                {"Status": "Ready", "Forecast SKU Count": 1}
            ]),
        },
        "forecast_dataset_id": dataset_id,
        "forecast_error_message": None,
    }
    monkeypatch.setattr(state.st, "session_state", values)
    monkeypatch.setattr(state, "restore_runtime_authority", lambda: None)
    calls = []

    def fake_prepare_default_inventory_forecasts(txns):
        calls.append(txns.copy())
        return (
            pd.DataFrame({"SKU": ["S-1"], "Stock": [10]}),
            pd.DataFrame({"SKU": ["S-1"]}),
            {"valid": True},
            pd.DataFrame({"SKU": ["S-1"]}),
            {
                "forecast_output": pd.DataFrame({
                    "SKU": ["S-1"],
                    "Category": ["Kitchenware"],
                    "Time": [pd.Timestamp("2026-04-02")],
                    "Method": ["Moving Average"],
                    "Forecast": [9],
                }),
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
                "category_validation_detail": pd.DataFrame([
                    {
                        "Category": "Kitchenware",
                        "Time": pd.Timestamp("2026-04-02"),
                        "Method": "Moving Average",
                        "Actual": 10,
                        "Forecast": 9,
                    }
                ]),
                "selection_status": pd.DataFrame([
                    {"Status": "Ready", "Forecast SKU Count": 1}
                ]),
            },
        )

    monkeypatch.setattr(
        state,
        "_prepare_default_inventory_forecasts",
        fake_prepare_default_inventory_forecasts,
    )

    state.ensure_derived_outputs_for_active_dataset()

    assert len(calls) == 1
    assert state.has_valid_forecast_for_active_dataset() is True
    assert values["forecast_dataset_id"] == dataset_id


    def test_persistence_error_message_does_not_blame_the_source_file(monkeypatch):
        rendered = []
        monkeypatch.setattr(components.st, "markdown", lambda content, **_kwargs: rendered.append(content))

        components.persistence_error_state()

        message = " ".join(rendered)
        assert "uploaded data passed validation" in message
        assert "database is temporarily unavailable" in message
        assert "Fix the items below" not in message
