"""Integration tests for Product Prioritization page and prescriptive state management."""

from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from return_refund_store import load_persisted_outputs, refresh_batch
from three_criterion_mca import Coverage, CRITERIA, RATE
from utils.state import (
    DEFAULT_STATE,
    DataStatus,
    _ensure_default_prescriptive_outputs,
    ensure_derived_outputs_for_active_dataset,
    get_mca_results,
    has_valid_prescriptive_for_active_dataset,
    set_prescriptive_results,
)


def test_load_persisted_outputs_roundtrip(tmp_path):
    """Verify that outputs persisted via refresh_batch can be reloaded via load_persisted_outputs."""
    db_path = tmp_path / "test_review.db"
    assert load_persisted_outputs(db_path) is None

    cov = Coverage("2026-04-01", "2026-04-24", "2026-04-01", "2026-04-24", "2026-10-15", "2026-10-16", True)
    sample_mca = pd.DataFrame([{"SKU": "SKU-001", "SKU Priority Score": 0.85, "Priority Rank": 1}])
    sample_risk = pd.DataFrame([{"SKU": "SKU-001", "Stock-Out Risk": "Low"}])
    sample_recs = pd.DataFrame([{"SKU": "SKU-001", "Recommended Quantity": 10}])
    sample_review = pd.DataFrame([{"Return ID": "R1", "product_key": "P1", "Return / Refund Status": "Request Refunded", "Review Decision": "Counted", "Review Reason": "Recorded Request Refunded outcome"}])

    def calc(records, policy):
        return {
            "mca_results": sample_mca,
            "risk_results": sample_risk,
            "recommendation_results": sample_recs,
            "return_request_review": sample_review,
        }

    refresh_batch(db_path, batch_type="return_refund", coverage=cov, calculate=calc)

    loaded = load_persisted_outputs(db_path)
    assert loaded is not None
    assert "mca_results" in loaded
    pd.testing.assert_frame_equal(loaded["mca_results"], sample_mca, check_dtype=False)
    assert "risk_results" in loaded
    pd.testing.assert_frame_equal(loaded["risk_results"], sample_risk, check_dtype=False)
    assert "recommendation_results" in loaded
    pd.testing.assert_frame_equal(loaded["recommendation_results"], sample_recs, check_dtype=False)


def test_ensure_default_prescriptive_outputs_loads_three_criterion_baseline(monkeypatch):
    """Verify that _ensure_default_prescriptive_outputs populates TA-approved baseline results."""
    from utils import state
    session = {}
    monkeypatch.setattr(state.st, "session_state", session)

    dummy_txns = pd.DataFrame([{"order_date": "2026-04-24", "Quantity": 1, "product_key": "P1"}])
    session["active_dataset_id"] = "active_test"

    _ensure_default_prescriptive_outputs(dummy_txns)

    mca = session.get("mca_results")
    assert mca is not None and not mca.empty
    assert len(mca) == 59
    assert set(CRITERIA).issubset(mca.columns)
    assert "SKU Priority Score" in mca.columns
    assert "Priority Level" in mca.columns
    assert session.get("three_criterion_active") is True
    assert session.get("risk_results") is not None
    assert session.get("recommendation_results") is not None


def test_product_prioritization_renders_three_criterion_results():
    """Verify that Product Prioritization displays ranking table, 3 criteria with equal weights."""
    from test_week3_prescriptive_pipeline import _pipeline_inputs
    page_path = Path(__file__).resolve().parents[1] / "pages/product_prioritization.py"
    app = AppTest.from_file(page_path)

    tx, analytics, forecasts, _ = _pipeline_inputs()

    three_dir = Path(__file__).resolve().parents[1] / "validation_outputs/three_criterion_mca"
    mca_results = pd.read_csv(three_dir / "mca_results.csv", dtype={"SKU": "string"})
    mca_audit = pd.read_csv(three_dir / "mca_audit.csv", dtype={"SKU": "string"})
    risk_results = pd.read_csv(three_dir / "risk_results.csv", dtype={"SKU": "string"})
    recs_results = pd.read_csv(three_dir / "recommendation_results.csv", dtype={"SKU": "string"})

    values = {
        **DEFAULT_STATE,
        "authenticated": True,
        "data_status": DataStatus.DATA_READY.value,
        "active_dataset_id": "test_dataset",
        "analytics_dataset_id": "test_dataset",
        "forecast_dataset_id": "test_dataset",
        "prepared_transactions": tx,
        "analytics_results": analytics,
        "forecast_results": forecasts,
        "mca_results": mca_results,
        "mca_audit": mca_audit,
        "risk_results": risk_results,
        "recommendation_results": recs_results,
        "three_criterion_active": True,
    }
    for k, v in values.items():
        app.session_state[k] = v

    app.run()
    assert not app.exception

    # Confirm ranking table is rendered
    ranking_table = next((t.value for t in app.dataframe if "Rank" in t.value.columns and "MCA Score" in t.value.columns), None)
    assert ranking_table is not None
    assert len(ranking_table) == 59
    assert ranking_table.iloc[0]["SKU"] == "SNRIOHK"
    assert ranking_table.iloc[0]["Rank"] == 1
    assert ranking_table.iloc[0]["Priority"] == "High"

    # Confirm equal-weights panel text
    markdown_text = " ".join(str(m.value) for m in app.markdown)
    assert "Sales Velocity" in markdown_text
    assert "Forecasted Demand" in markdown_text
    assert "33.33%" in markdown_text


def test_product_prioritization_empty_state_diagnostic_ui(monkeypatch):
    """Verify that when MCA results are genuinely empty, the diagnostic checklist and business guidance render cleanly."""
    from test_week3_prescriptive_pipeline import _pipeline_inputs
    import utils.state
    # Prevent auto-loading baseline so we can test the empty state UI
    monkeypatch.setattr(utils.state, "_ensure_default_prescriptive_outputs", lambda txns: None)

    page_path = Path(__file__).resolve().parents[1] / "pages/product_prioritization.py"
    app = AppTest.from_file(page_path)

    tx, analytics, forecasts, _ = _pipeline_inputs()

    values = {
        **DEFAULT_STATE,
        "authenticated": True,
        "data_status": DataStatus.DATA_READY.value,
        "active_dataset_id": "test_dataset",
        "analytics_dataset_id": "test_dataset",
        "forecast_dataset_id": "test_dataset",
        "prepared_transactions": tx,
        "analytics_results": analytics,
        "forecast_results": forecasts,
        "mca_results": pd.DataFrame(),  # Empty MCA
        "mca_audit": None,
        "risk_results": None,
        "recommendation_results": None,
        "inventory_crosswalk": None,
        "three_criterion_active": False,
    }
    for k, v in values.items():
        app.session_state[k] = v

    app.run()
    assert not app.exception

    markdown_text = " ".join(str(m.value) for m in app.markdown)
    assert "Data Readiness & Guidance" in markdown_text
    assert "1. Historical Sales Transactions" in markdown_text
    assert "2. Current Stock Snapshot & Crosswalk" in markdown_text
    assert "3. SKU Demand Forecasts" in markdown_text
    assert "4. Return/Refund Evidence (TA-Approved)" in markdown_text
    assert "Next Steps for the Business Owner" in markdown_text
    assert "Data Upload & ETL" in markdown_text
