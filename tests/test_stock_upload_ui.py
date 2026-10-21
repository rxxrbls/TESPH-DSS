"""Regression coverage for the interactive current-stock workflow."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import etl_inventory
import forecasting_pipeline
import prescriptive_pipeline
import utils.components as components
from utils.state import DEFAULT_STATE, DataStatus
from etl_config import FINAL_SCHEMAS
from star_schema_db import INGESTION_BATCH_COLUMNS, LOAD_ORDER, load_runtime_snapshot


PAGE_PATH = Path(__file__).resolve().parents[1] / "pages" / "data_upload.py"


def _validation(*, valid: bool = True) -> dict:
    checks = pd.DataFrame({"valid": [valid, valid], "stock_valid": [valid, valid]})
    return {
        "valid": valid,
        "row_count": len(checks),
        "row_checks": checks,
        "stock_as_of": date(2026, 9, 9),
    }


def _crosswalk() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_key": ["P-1", "P-2"],
            "SKU": ["SKU-1", "SKU-2"],
            "Stock": [10, 20],
            "match_status": ["candidate", "review_required"],
            "mapping_review_required": [False, True],
            "stock_valid": [True, True],
            "stock_as_of": [pd.Timestamp("2026-09-09")] * 2,
        }
    )


def _forecast() -> dict[str, pd.DataFrame]:
    return {
        "forecast_output": pd.DataFrame(
            {
                "SKU": ["SKU-1"],
                "Product": ["Product 1"],
                "Category": ["Category"],
                "Time": [pd.Timestamp("2026-09-10")],
                "Forecast": [7.0],
            }
        )
    }


def _prescriptive() -> dict[str, pd.DataFrame]:
    return {
        "risk_results": pd.DataFrame({"SKU": ["SKU-1"]}),
        "mca_results": pd.DataFrame({"SKU": ["SKU-1"]}),
        "recommendation_results": pd.DataFrame({"SKU": ["SKU-1"]}),
    }


def _run_stock_page(
    monkeypatch,
    *,
    forecast_error: str | None = None,
    validation_valid: bool = True,
    missing_star_schema: bool = False,
) -> AppTest:
    """Run the real page with deterministic pipeline boundaries."""
    monkeypatch.setattr(components, "guard_protected_page", lambda: None)
    monkeypatch.setattr(components, "render_page_shell", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(etl_inventory, "load_current_inventory", lambda _config: pd.DataFrame({"SKU": ["SKU-1"]}))
    monkeypatch.setattr(
        etl_inventory,
        "validate_current_inventory",
        lambda _inventory, _config: _validation(valid=validation_valid),
    )
    monkeypatch.setattr(etl_inventory, "build_inventory_crosswalk", lambda *_args: _crosswalk())
    monkeypatch.setattr(
        prescriptive_pipeline,
        "build_sku_mapping_from_stock_upload",
        lambda *_args, **_kwargs: (pd.DataFrame({"SKU": ["SKU-1"], "active": [True]}), pd.DataFrame()),
    )
    if forecast_error:
        def _raise_forecast(*_args, **_kwargs):
            raise ValueError(forecast_error)

        monkeypatch.setattr(forecasting_pipeline, "run_forecasting_pipeline", _raise_forecast)
    else:
        monkeypatch.setattr(forecasting_pipeline, "run_forecasting_pipeline", lambda *_args, **_kwargs: _forecast())
    monkeypatch.setattr(prescriptive_pipeline, "run_prescriptive_pipeline", lambda *_args, **_kwargs: _prescriptive())

    app = AppTest.from_file(PAGE_PATH, default_timeout=30)
    for key, value in DEFAULT_STATE.items():
        app.session_state[key] = value
    app.session_state["data_status"] = DataStatus.DATA_READY.value
    if not missing_star_schema:
        app.session_state["star_schema"] = {"dim_product": pd.DataFrame({"product_key": ["P-1"]})}
    app.session_state["prepared_transactions"] = pd.DataFrame({"Order ID": ["O-1"]})
    app.session_state["analytics_results"] = {}
    return app.run()


def _select_and_confirm_stock(app: AppTest) -> AppTest:
    app.file_uploader[1].set_value(("current-stock.xlsx", b"test workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    app.run()
    app.date_input[0].set_value(date(2026, 9, 9))
    app.checkbox[0].check()
    app.checkbox[1].check()
    return app.run()


def test_validate_stock_data_click_publishes_a_persistent_success_outcome(monkeypatch):
    app = _select_and_confirm_stock(_run_stock_page(monkeypatch))

    assert not app.exception
    assert app.button[0].label == "Validate stock data"
    app.button[0].click().run()

    assert not app.exception
    assert any(message.value == "Current-stock snapshot validated and connected outputs refreshed." for message in app.success)
    assert app.session_state["inventory_validation"]["row_count"] == 2
    assert len(app.session_state["risk_results"]) == 1
    app.run()
    assert any(message.value == "Current-stock snapshot validated and connected outputs refreshed." for message in app.success)


def test_stock_upload_restores_dimension_from_existing_runtime_snapshot(monkeypatch, tmp_path):
    database = tmp_path / "active_transactions.db"
    stars = {
        table: pd.DataFrame(columns=FINAL_SCHEMAS[table])
        for table in LOAD_ORDER
    }
    stars["dim_product"] = pd.DataFrame(
        [{"product_key": "P-1", **{column: None for column in FINAL_SCHEMAS["dim_product"] if column != "product_key"}}],
        columns=FINAL_SCHEMAS["dim_product"],
    )
    prepared = pd.DataFrame(columns=FINAL_SCHEMAS["prepared_transactions"])
    batches = pd.DataFrame(columns=INGESTION_BATCH_COLUMNS)
    load_runtime_snapshot(
        stars,
        prepared,
        batches,
        {"dataset_id": "dataset-1"},
        database,
    )
    monkeypatch.setattr("etl_config.RUNTIME_DB_PATH", database)

    app = _run_stock_page(monkeypatch, missing_star_schema=True)
    assert not app.exception
    assert app.session_state["star_schema"]["dim_product"].loc[0, "product_key"] == "P-1"

    app = _select_and_confirm_stock(app)
    app.button[0].click().run()

    assert not app.exception
    assert any(
        message.value == "Current-stock snapshot validated and connected outputs refreshed."
        for message in app.success
    )


def test_stock_workflow_shows_the_downstream_failure_and_retains_validated_snapshot(monkeypatch):
    app = _select_and_confirm_stock(_run_stock_page(monkeypatch, forecast_error="No eligible SKU forecast is available"))

    app.button[0].click().run()

    assert not app.exception
    assert any("Current-stock processing did not complete." in message.value for message in app.error)
    assert any("Reason: No eligible SKU forecast is available" in message.value for message in app.caption)
    assert app.session_state["inventory_validation"]["row_count"] == 2
    assert app.session_state["forecast_results"] is None
    assert app.session_state["risk_results"] is None


def test_stock_validation_failure_is_visible_without_publishing_stock_or_downstream_results(monkeypatch):
    app = _select_and_confirm_stock(_run_stock_page(monkeypatch, validation_valid=False))

    app.button[0].click().run()

    assert not app.exception
    assert any("Current-stock validation failed." in message.value for message in app.error)
    assert app.session_state["inventory_validation"] is None
    assert app.session_state["forecast_results"] is None
    assert app.session_state["risk_results"] is None


def test_future_stock_asof_date_blocks_validation(monkeypatch):
    app = _select_and_confirm_stock(_run_stock_page(monkeypatch))
    app.date_input[0].set_value(date.today() + timedelta(days=1))
    app = app.run()

    assert not app.exception
    assert any("cannot be in the future" in message.value for message in app.error)
    assert not any(button.label == "Validate stock data" for button in app.button)
    assert app.session_state["inventory_validation"] is None


def test_stock_workflow_renders_an_explicit_running_status(monkeypatch):
    source = PAGE_PATH.read_text(encoding="utf-8")

    assert 'st.status("Validating the selected current-stock snapshot...", expanded=True)' in source
    assert "Refreshing the SKU forecast using the active consolidated transaction history." in source


def test_missing_snapshot_date_defaults_to_latest_transaction_date(monkeypatch):
    app = _run_stock_page(monkeypatch)
    app.session_state["prepared_transactions"] = pd.DataFrame(
        {"order_date": ["2026-09-08", "2026-09-12", "invalid"]}
    )
    app.file_uploader[1].set_value(
        ("current-stock.xlsx", b"test workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    )
    app.run()

    assert not app.exception
    assert app.date_input[0].value == date(2026, 9, 12)
    assert any("latest transaction date as the TA-approved estimate" in item.value for item in app.caption)
