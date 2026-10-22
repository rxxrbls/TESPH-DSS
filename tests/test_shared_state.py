import pandas as pd
import pytest

import utils.analytics_display as analytics_display
import utils.state as state


def test_new_dataset_clears_stock_dependent_state(monkeypatch):
    values = {
        "inventory_data": pd.DataFrame({"stock": [4]}),
        "inventory_crosswalk": pd.DataFrame({"product_key": ["old"]}),
        "inventory_validation": {"valid": True},
        "risk_results": pd.DataFrame({"Stock-Out Risk": ["High"]}),
        "mca_results": pd.DataFrame({"SKU Priority Score": [0.8]}),
        "mca_sensitivity": pd.DataFrame({"Rank Change": [1]}),
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
        "mca_audit": None,
        "mca_sensitivity": None,
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


def test_integrated_forecast_uses_active_catalog_mapping(monkeypatch):
    transactions = pd.DataFrame({"Order ID": ["O-1"]})
    mapping = pd.DataFrame({"product_key": ["P-1"], "SKU": ["SKU-1"]})
    review = pd.DataFrame({"Reason": ["Eligible current catalog match"]})
    captured = {}

    monkeypatch.setattr(
        "active_inventory.build_active_mapping",
        lambda frame: (mapping, review) if frame is transactions else pytest.fail("wrong transaction input"),
    )

    def run_forecast(frame, *, mapping=None):
        captured["frame"] = frame
        captured["mapping"] = mapping
        return {"forecast_output": pd.DataFrame({"SKU": ["SKU-1"]})}

    monkeypatch.setattr("forecasting_pipeline.run_forecasting_pipeline", run_forecast)

    result = state.run_active_forecasting_pipeline(transactions)

    assert captured["frame"] is transactions
    assert captured["mapping"] is mapping
    assert result["inventory_review"] is review
    assert result["forecast_output"]["SKU"].tolist() == ["SKU-1"]


@pytest.mark.parametrize(
    ("include_analytics", "include_forecast", "expected"),
    [
        (True, False, {"analytics"}),
        (False, True, {"forecast"}),
        (True, True, {"analytics", "forecast"}),
    ],
)
def test_derived_output_initializer_computes_only_requested_families(
    monkeypatch, include_analytics, include_forecast, expected
):
    values = {
        "active_dataset_id": "dataset-a",
        "data_status": state.DataStatus.DATA_READY.value,
        "prepared_transactions": pd.DataFrame({"Order ID": ["O-1"]}),
    }
    calls = set()
    monkeypatch.setattr(state.st, "session_state", values)
    monkeypatch.setattr(state, "restore_runtime_authority", lambda: None)

    def analytics(_transactions):
        calls.add("analytics")
        return {"sales_summary": pd.DataFrame({"Gross Revenue": [1]})}

    def forecast(_transactions):
        calls.add("forecast")
        return {"forecast_output": pd.DataFrame({"SKU": ["SKU-1"]})}

    monkeypatch.setattr("analytics_pipeline.run_analytics_pipeline", analytics)
    monkeypatch.setattr(state, "run_active_forecasting_pipeline", forecast)

    state.ensure_derived_outputs_for_active_dataset(
        include_analytics=include_analytics,
        include_forecast=include_forecast,
    )

    assert calls == expected


    def test_persistence_error_message_does_not_blame_the_source_file(monkeypatch):
        rendered = []
        monkeypatch.setattr(components.st, "markdown", lambda content, **_kwargs: rendered.append(content))

        components.persistence_error_state()

        message = " ".join(rendered)
        assert "uploaded data passed validation" in message
        assert "database is temporarily unavailable" in message
        assert "Fix the items below" not in message
