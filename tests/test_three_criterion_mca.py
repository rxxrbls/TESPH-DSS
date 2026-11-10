from dataclasses import replace
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from three_criterion_mca import Coverage, RATE, CRITERIA, evaluate_requests, rank_scenarios
from return_refund_store import refresh_batch, load_evidence


def inputs():
    tx = pd.DataFrame({
        "Order ID": ["O1", "O2"], "Order Status": ["Completed"] * 2,
        "SKU Reference No.": ["A", "B"], "Product Name": ["P1", "P2"],
        "Variation Name": ["", ""], "product_key": ["p1", "p2"],
        "final_base_product_name": ["P1", "P2"], "final_category": ["C"] * 2,
        "order_date": ["2026-04-24"] * 2, "Quantity": [10, 20],
        "Returned quantity": [0, 0], "Deal Price": [1, 1], "Total Buyer Payment": [10, 20],
        "is_completed": [True, True], "is_cancelled": [False, False], "is_returned": [False, False],
    })
    rr = pd.DataFrame({
        "Return ID": ["R1"], "Order ID": ["O1"], "Product Name": ["P1"],
        "Variation Name": [""], "product_key": ["p1"],
        "Return Creation Time": ["2026-04-24 23:59:59"],
        "Return / Refund Status": ["Request Refunded"], "Return Quantity": [2],
        "Return/Refund Solution": ["Refund Only"], "Refund Completed Time": [""],
    })
    mapping = pd.DataFrame({"product_key": ["p1", "p2"], "SKU": ["A", "B"]})
    coverage = Coverage("2026-04-01", "2026-04-24", "2026-04-01", "2026-04-24",
                        "2026-10-15", "2026-10-16", True)
    return tx, rr, mapping, coverage


def test_hand_calculation_matching_window_and_blank_completion():
    tx, rr, mapping, cov = inputs()
    audit, review = evaluate_requests(tx, rr, mapping, cov)
    assert audit[RATE].tolist() == [20, 0]
    assert review["Missing Completion Date"].tolist() == [True]
    rr["Return Creation Time"] = "2026-04-25"
    audit, review = evaluate_requests(tx, rr, mapping, cov)
    assert audit[RATE].tolist() == [0, 0]
    assert review["Review Decision"].tolist() == ["Excluded"]
    audit, _ = evaluate_requests(tx, rr, mapping, replace(cov, established=False))
    assert audit[RATE].isna().all()


def test_source_sku_preserved_separately_from_catalog_and_leading_zero_ids():
    tx, rr, mapping, cov = inputs()
    rr["SKU"] = "source sku"
    tx.loc[0, "Order ID"] = "0001"
    rr["Order ID"] = "0001"
    audit, review = evaluate_requests(tx, rr, mapping, cov)
    assert review.iloc[0]["Source SKU"] == "source sku"
    assert review.iloc[0]["SKU"] == "A"
    assert audit.iloc[0][RATE] == 20


@pytest.mark.parametrize("status", ["Dispute Approved", "Dispute Rejected", "Unknown", "Under Review"])
def test_disputes_do_not_resolve_from_completion_date(status):
    tx, rr, mapping, cov = inputs()
    rr["Return / Refund Status"] = status
    rr["Refund Completed Time"] = "2026-04-24"
    audit, review = evaluate_requests(tx, rr, mapping, cov)
    assert pd.isna(audit.iloc[0][RATE])
    assert audit.iloc[1][RATE] == 0
    assert review.iloc[0]["Review Decision"] == "Unresolved"


def test_repeated_requests_not_summed_but_cancelled_attempt_can_be_followed():
    tx, rr, mapping, cov = inputs()
    rr = pd.concat([rr, rr.assign(**{"Return ID": "R2"})], ignore_index=True)
    audit, _ = evaluate_requests(tx, rr, mapping, cov)
    assert pd.isna(audit.iloc[0][RATE])
    rr.loc[0, "Return / Refund Status"] = "Request Cancelled"
    audit, _ = evaluate_requests(tx, rr, mapping, cov)
    assert audit.iloc[0][RATE] == 20


@pytest.mark.parametrize("quantity", [11, -1, "", np.inf, .5])
def test_invalid_or_excess_units_exclude_sku(quantity):
    tx, rr, mapping, cov = inputs()
    rr["Return Quantity"] = quantity
    audit, _ = evaluate_requests(tx, rr, mapping, cov)
    assert pd.isna(audit.iloc[0][RATE])


def test_normalization_excludes_missing_and_preserves_constant_rule():
    data = pd.DataFrame({"SKU": ["A", "B", "X"], "Sales Velocity": [1, 3, 1000],
                         "Forecasted Demand": [0, 0, 1000], RATE: [20, 0, np.nan]})
    scenarios, comparison, summary = rank_scenarios(data)
    ranked = scenarios["equal_thirds"].set_index("SKU")
    assert list(ranked.index) == ["B", "A"]
    assert ranked.loc["B", "SKU Priority Score"] == pytest.approx(5 / 6)
    assert ranked.loc["A", "SKU Priority Score"] == pytest.approx(1 / 6)
    assert ranked["Normalized Forecasted Demand"].eq(.5).all()
    assert summary["pearson"] is None
    assert summary["excluded_skus"] == 1


def test_weight_sensitivity_detects_a_real_priority_reversal():
    data = pd.DataFrame({"SKU": ["A", "B", "C"], "Sales Velocity": [10, 4, 0],
                         "Forecasted Demand": [10, 4, 0], RATE: [100, 0, 100]})
    scenarios, comparison, summary = rank_scenarios(data)
    assert scenarios["equal_thirds"].iloc[0]["SKU"] == "A"
    assert scenarios["volume_quality"].iloc[0]["SKU"] == "B"
    assert summary["pearson"] == pytest.approx(1)
    assert summary["spearman"] == pytest.approx(1)
    assert summary["rank_changes"] == 2
    assert summary["group_changes"] == 2


def test_refresh_persistence_repeat_partial_resolution_and_rollback(tmp_path):
    tx, rr, mapping, cov = inputs()
    path = tmp_path / "review.db"
    def calculate(records, policy):
        audit, review = evaluate_requests(tx, records, mapping, Coverage(**policy))
        return {"mca_audit": audit, "return_request_review": review}
    rr["Return / Refund Status"] = "Dispute Rejected"
    refresh_batch(path, batch_type="return_refund", snapshot=rr, coverage=cov, calculate=calculate)
    refresh_batch(path, batch_type="sales", calculate=calculate)
    result = refresh_batch(path, batch_type="stock", snapshot=rr.iloc[:0], calculate=calculate)
    assert pd.isna(result["mca_audit"].iloc[0][RATE])
    def fail(*_):
        raise ValueError("calculation failed")
    with pytest.raises(ValueError):
        refresh_batch(path, batch_type="sales", calculate=fail)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 3
    rr["Return / Refund Status"] = "Request Refunded"
    result = refresh_batch(path, batch_type="return_refund", snapshot=rr, calculate=calculate)
    assert result["mca_audit"].iloc[0][RATE] == 20
    with sqlite3.connect(path) as db:
        last = json.loads(db.execute("SELECT payload FROM audit ORDER BY event_id DESC").fetchone()[0])
    assert last["previous_decision"] == "Unresolved"
    assert last["current_decision"] == "Counted"
    assert load_evidence(path)[0].iloc[0]["Return / Refund Status"] == "Request Refunded"


def test_three_criterion_connected_pipeline_and_frontend(tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from utils.state import DEFAULT_STATE, DataStatus
    from test_week3_prescriptive_pipeline import _pipeline_inputs
    from mca_refresh import refresh_connected
    tx, analytics, forecasts, stock = _pipeline_inputs()
    tx["Variation Name"] = ""
    forecasts["sku_mapping"] = pd.DataFrame({
        "product_key": ["P1", "P2"], "SKU": ["SKU-A", "SKU-B"],
        "Product": ["Item A", "Item B"], "Category": ["A", "B"],
        "active": [True, True], "category_active": [True, True],
        "client_approved": [False, False], "catalog_active": [True, True],
    })
    _, rr, _, _ = inputs()
    rr["Product Name"] = "Item A"
    rr["product_key"] = "P1"
    rr["Return Creation Time"] = "2026-09-02"
    rr["Return Quantity"] = 1
    cov = Coverage("2026-09-01", "2026-09-02", "2026-09-01", "2026-09-02",
                   "2026-10-15", "2026-10-16", True)
    result = refresh_connected(tx, analytics, forecasts, stock, snapshot=rr,
        coverage=cov, batch_type="return_refund", store_path=tmp_path / "review.db", as_of="2026-09-28")
    scores = result["mca_results"].set_index("SKU")
    assert scores.loc["SKU-A", RATE] == 20
    assert scores.loc["SKU-B", "SKU Priority Score"] == 1
    assert "Profit Margin" not in scores and "Supplier Lead Time" not in scores
    assert result["recommendation_results"]["SKU Priority Score"].notna().all()
    repeat = refresh_connected(tx, analytics, forecasts, stock, batch_type="stock",
        store_path=tmp_path / "review.db", as_of="2026-09-28")
    pd.testing.assert_frame_equal(repeat["mca_results"], result["mca_results"])
    with sqlite3.connect(tmp_path / "review.db") as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 2
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "pages/product_prioritization.py")
    for key, value in {**DEFAULT_STATE, "authenticated": True,
        "data_status": DataStatus.DATA_READY.value, "active_dataset_id": "test",
        "forecast_dataset_id": "test", "analytics_dataset_id": "test", "prepared_transactions": tx,
        "analytics_results": analytics, "forecast_results": forecasts, **result}.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    shown = next(table.value for table in app.dataframe if "SKU Priority Score" in table.value)
    pd.testing.assert_frame_equal(shown, result["mca_results"], check_dtype=False)
    assert any("historical validation accepted" in x.value for x in app.caption)


def test_assessment_dates_cannot_disagree_or_use_a_later_forecast():
    from test_week3_prescriptive_pipeline import _pipeline_inputs
    from prescriptive_pipeline import run_prescriptive_pipeline
    tx, analytics, forecasts, stock = _pipeline_inputs()
    tx["Variation Name"] = ""
    cov = Coverage("2026-09-01", "2026-09-02", "2026-09-01", "2026-09-02",
                   "2026-10-15", "2026-10-16", True)
    with pytest.raises(ValueError, match="must match"):
        run_prescriptive_pipeline(tx, analytics, forecasts, stock, mca_coverage=cov,
            mca_period_end="2026-09-03", as_of="2026-09-28")
    forecasts["forecast_output"]["Time"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="active forecast has no SKU mapping"):
        run_prescriptive_pipeline(tx, analytics, forecasts, stock, mca_coverage=cov, as_of="2026-09-28")

def test_regenerated_forecast_with_wrong_start_date_is_rejected(monkeypatch):
    from test_week3_prescriptive_pipeline import _pipeline_inputs
    from prescriptive_pipeline import run_prescriptive_pipeline
    import sku_forecasting

    tx, analytics, forecasts, stock = _pipeline_inputs()
    tx["Variation Name"] = ""
    forecasts["sku_mapping"] = pd.DataFrame({
        "product_key": ["P1", "P2"], "SKU": ["SKU-A", "SKU-B"],
        "Product": ["Item A", "Item B"], "Category": ["A", "B"],
        "active": [True, True], "category_active": [True, True],
        "client_approved": [False, False], "catalog_active": [True, True],
    })

    cov = Coverage(
        "2026-09-01", "2026-09-02",
        "2026-09-01", "2026-09-02",
        "2026-10-15", "2026-10-16", True
    )

    # Force the original forecast to have an incorrect start date.
    forecasts["forecast_output"]["Time"] += pd.Timedelta(days=1)

    # Simulate regeneration returning a nonempty but incorrectly dated forecast.
    def fake_regeneration(*args, **kwargs):
        return {
            "forecast_output": pd.DataFrame({
                "Time": [pd.Timestamp("2026-09-05")],
                "SKU": ["SKU-A"],
                "Forecast": [1.0],
            })
        }

    monkeypatch.setattr(
        sku_forecasting, "run_sku_forecasting", fake_regeneration
    )

    with pytest.raises(
        ValueError,
        match="Regenerated forecast dates do not exactly cover"
    ):
        run_prescriptive_pipeline(
            tx,
            analytics,
            forecasts,
            stock,
            mca_coverage=cov,
            as_of="2026-09-28",
        )

def test_regenerated_forecast_with_correct_start_date_is_accepted(monkeypatch):
    from test_week3_prescriptive_pipeline import _pipeline_inputs
    from prescriptive_pipeline import run_prescriptive_pipeline
    import sku_forecasting

    tx, analytics, forecasts, stock = _pipeline_inputs()
    tx["Variation Name"] = ""
    forecasts["sku_mapping"] = pd.DataFrame({
        "product_key": ["P1", "P2"], "SKU": ["SKU-A", "SKU-B"],
        "Product": ["Item A", "Item B"], "Category": ["A", "B"],
        "active": [True, True], "category_active": [True, True],
        "client_approved": [False, False], "catalog_active": [True, True],
    })

    cov = Coverage(
        "2026-09-01", "2026-09-02",
        "2026-09-01", "2026-09-02",
        "2026-10-15", "2026-10-16", True
    )

    # Make the original forecast start on the wrong date.
    forecasts["forecast_output"]["Time"] += pd.Timedelta(days=1)

    # Return a correctly dated forecast during regeneration.
    def fake_regeneration(*args, **kwargs):
        assert pd.Timestamp(kwargs["coverage_end"]) == pd.Timestamp("2026-09-02")
        regenerated = {
            key: value.copy() if isinstance(value, pd.DataFrame) else value
            for key, value in forecasts.items()
        }
        regenerated["forecast_output"]["Time"] = (
            pd.to_datetime(regenerated["forecast_output"]["Time"])
            - pd.Timedelta(days=1)
        )
        return regenerated

    monkeypatch.setattr(
        sku_forecasting, "run_sku_forecasting", fake_regeneration
    )

    result = run_prescriptive_pipeline(
        tx,
        analytics,
        forecasts,
        stock,
        mca_coverage=cov,
        as_of="2026-09-28",
    )

    assert result is not None
    assert "mca_results" in result
    assert not result["mca_results"].empty


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("stock_2026-09-09.xlsx", "2026-09-09"),
        ("stock_2026_09_09.xlsx", "2026-09-09"),
        ("stock_2026-02-30.xlsx", None),
        ("stock_2027_01_01.xlsx", None),
        ("stock_2026-9-09.xlsx", None),
    ],
)
def test_inventory_snapshot_date_filename_detection(filename, expected):
    from datetime import date
    from utils.stock_validation import snapshot_date_from_filename

    result = snapshot_date_from_filename(filename, today=date(2026, 12, 31))
    assert (result.isoformat() if result else None) == expected
