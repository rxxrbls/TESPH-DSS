"""End-to-end backend integration tests for final defense readiness across full and partial datasets."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from analytics_calculations import prepare_transactions
from analytics_data import load_transactions
from etl import load_final_table
from etl_config import CURRENT_INVENTORY_SOURCE, FINAL_OUTPUT_DIR, InventoryConfig
from etl_inventory import (
    build_inventory_crosswalk,
    load_current_inventory,
    validate_current_inventory,
)
from forecasting_pipeline import run_forecasting_pipeline
from mca_refresh import compute_connected_three_criterion_prescriptive
from methodology_config import ForecastConfig
from prescriptive_pipeline import build_sku_mapping_from_stock_upload
from sku_forecasting import backtest_sku


def test_prepare_transactions_cache_is_fast_and_mutation_safe():
    txns = load_transactions()
    assert len(txns) > 200_000

    # First call populates cache; second call hits cache
    t_first = time.perf_counter()
    first = prepare_transactions(txns)
    first_elapsed = time.perf_counter() - t_first

    t0 = time.perf_counter()
    second = prepare_transactions(txns)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.65, f"Cached prepare_transactions took {elapsed:.3f}s (expected < 0.65s)"
    assert elapsed < first_elapsed, f"Cached call ({elapsed:.3f}s) should be faster than uncached ({first_elapsed:.3f}s)"
    assert first is not second
    pd.testing.assert_frame_equal(first, second)

    # Mutating returned copy must not corrupt cached frame
    first.loc[first.index[0], "Gross Revenue"] = -999999.0
    third = prepare_transactions(txns)
    assert third.loc[third.index[0], "Gross Revenue"] != -999999.0


def test_backtest_sku_fast_path_matches_expected_metrics():
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    demand = np.linspace(2.0, 14.0, len(dates)) + np.sin(np.arange(len(dates)))
    sku_history = pd.DataFrame(
        {
            "Time": dates,
            "Demand": demand,
            "SKU": "SKU-FAST-01",
            "Product": "Test Product",
            "Category": "Electrical",
        }
    )
    cfg = ForecastConfig()
    t0 = time.perf_counter()
    detail = backtest_sku(sku_history, cfg)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.15, f"backtest_sku took {elapsed:.3f}s for 1 SKU"
    assert not detail.empty
    assert set(detail["Method"]) == {"Moving Average", "Exponential Smoothing", "Linear Regression"}
    assert detail["Forecast"].notna().all()
    assert detail["Actual"].notna().all()


def test_full_baseline_stock_crosswalk_forecast_mca_and_replenishment_workflow():
    txns = load_transactions()
    dim_product = load_final_table("dim_product", FINAL_OUTPUT_DIR)
    stock_as_of = pd.Timestamp("2026-09-09").date()
    as_of = pd.Timestamp("2026-09-09")

    inv_cfg = InventoryConfig(
        source_path=CURRENT_INVENTORY_SOURCE,
        stock_as_of=stock_as_of,
        stock_definition_confirmed=True,
    )
    inventory = load_current_inventory(inv_cfg)
    validation = validate_current_inventory(inventory, inv_cfg)
    crosswalk = build_inventory_crosswalk(inventory, dim_product, inv_cfg)

    assert validation["valid"] is True
    assert len(inventory) == 1980

    status_counts = crosswalk["match_status"].value_counts().to_dict()
    assert status_counts.get("candidate", 0) == 1092
    assert status_counts.get("unmatched", 0) == 834
    assert status_counts.get("review_required", 0) == 54

    mapping, inventory_audit = build_sku_mapping_from_stock_upload(
        txns,
        crosswalk,
        stock_as_of=stock_as_of,
        as_of=as_of,
    )
    assert int(mapping["active"].sum()) == 65

    forecasts = run_forecasting_pipeline(txns, mapping=mapping)
    forecasts["inventory_review"] = inventory_audit
    forecasts["sku_mapping"] = mapping

    assert len(forecasts["best_methods"]) == 60
    assert int(forecasts["eligibility"]["active"].fillna(False).sum()) == 65
    assert int(forecasts["eligibility"]["Eligible"].fillna(False).sum()) == 60

    prescriptive = compute_connected_three_criterion_prescriptive(
        txns,
        {},
        forecasts,
        crosswalk,
        as_of=as_of,
    )
    risk_df = prescriptive["risk_results"]
    mca_df = prescriptive["mca_results"]
    rec_df = prescriptive["recommendation_results"]

    assert len(risk_df) == 60
    assert not mca_df.empty
    assert len(mca_df) >= 59
    assert len(rec_df) == 60
    assert "Priority Level" in rec_df.columns
    assert int(rec_df["Priority Level"].notna().sum()) >= 59


def test_partial_single_month_dataset_stock_upload_produces_valid_mca_and_replenishment():
    """Simulates uploading a subset dataset where fewer stock rows (~67+) match and ~15+ SKUs are forecasted."""
    full_txns = load_transactions()
    full_dim = load_final_table("dim_product", FINAL_OUTPUT_DIR)

    # Select a ~75-day window ending at max order_date so SKUs with sales across the window pass the 44-day history check
    dates = pd.to_datetime(full_txns["order_date"], errors="coerce")
    max_date = dates.max()
    min_cutoff = max_date - pd.Timedelta(days=75)
    partial_txns = full_txns.loc[(dates >= min_cutoff) & (dates <= max_date)].copy().reset_index(drop=True)
    assert 0 < len(partial_txns) < len(full_txns)

    # Subset dim_product to product_keys appearing in partial_txns (simulating Replace mode ETL)
    active_keys = set(partial_txns["product_key"].dropna().astype(str))
    partial_dim = full_dim.loc[full_dim["product_key"].astype(str).isin(active_keys)].copy().reset_index(drop=True)

    stock_as_of = pd.Timestamp("2026-09-09").date()
    as_of = pd.Timestamp("2026-09-09")
    inv_cfg = InventoryConfig(
        source_path=CURRENT_INVENTORY_SOURCE,
        stock_as_of=stock_as_of,
        stock_definition_confirmed=True,
    )
    inventory = load_current_inventory(inv_cfg)
    validation = validate_current_inventory(inventory, inv_cfg)
    crosswalk = build_inventory_crosswalk(inventory, partial_dim, inv_cfg)
    assert validation["valid"] is True

    mapping, inventory_audit = build_sku_mapping_from_stock_upload(
        partial_txns,
        crosswalk,
        stock_as_of=stock_as_of,
        as_of=as_of,
    )
    forecasts = run_forecasting_pipeline(partial_txns, mapping=mapping)
    forecasts["inventory_review"] = inventory_audit
    forecasts["sku_mapping"] = mapping

    forecasted_sku_count = len(forecasts["best_methods"])
    assert forecasted_sku_count > 0

    prescriptive = compute_connected_three_criterion_prescriptive(
        partial_txns,
        {},
        forecasts,
        crosswalk,
        as_of=as_of,
    )
    risk_df = prescriptive["risk_results"]
    mca_df = prescriptive["mca_results"]
    rec_df = prescriptive["recommendation_results"]

    assert len(risk_df) == forecasted_sku_count
    assert not mca_df.empty, "3-criterion MCA must not be empty on partial dataset upload"
    assert len(rec_df) == forecasted_sku_count
    assert int(rec_df["Priority Level"].notna().sum()) == len(mca_df)


def test_forecast_display_renders_mixed_zero_holdout_note_and_eligibility_audit():
    metrics = pd.DataFrame(
        [
            {"SKU": "SKU-ACTIVE", "Method": "Moving Average", "MAE": 1.25, "RMSE": 1.5, "MAPE": 12.0, "Raw MAPE": 12.0, "R2": 0.5, "MAPE Status": "Adjusted (floor=1)"},
            {"SKU": "SKU-DORMANT", "Method": "Moving Average", "MAE": 0.0, "RMSE": 0.0, "MAPE": 0.0, "Raw MAPE": np.nan, "R2": np.nan, "MAPE Status": "Adjusted (floor=1)"},
        ]
    )
    best = pd.DataFrame(
        [
            {"SKU": "SKU-ACTIVE", "Method": "Moving Average"},
            {"SKU": "SKU-DORMANT", "Method": "Moving Average"},
        ]
    )
    detail = pd.DataFrame(
        [
            {"SKU": "SKU-ACTIVE", "Method": "Moving Average", "Origin": "2026-08-25", "Time": "2026-08-26", "Actual": 3.0, "Forecast": 2.0},
            {"SKU": "SKU-ACTIVE", "Method": "Moving Average", "Origin": "2026-08-25", "Time": "2026-08-27", "Actual": 5.0, "Forecast": 4.0},
            {"SKU": "SKU-DORMANT", "Method": "Moving Average", "Origin": "2026-08-25", "Time": "2026-08-26", "Actual": 0.0, "Forecast": 0.0},
            {"SKU": "SKU-DORMANT", "Method": "Moving Average", "Origin": "2026-08-25", "Time": "2026-08-27", "Actual": 0.0, "Forecast": 0.0},
        ]
    )
    eligibility = pd.DataFrame(
        [
            {"SKU": "SKU-ACTIVE", "Eligible": True, "Reason": "Eligible"},
            {"SKU": "SKU-DORMANT", "Eligible": True, "Reason": "Eligible"},
            {"SKU": "SKU-SHORT", "Eligible": False, "Reason": "Insufficient daily history (18 < 44)"},
        ]
    )
    results = {
        "validation_metrics": metrics,
        "best_methods": best,
        "validation_detail": detail,
        "eligibility": eligibility,
    }

    def _app_script():
        import streamlit as st
        from utils.forecast_display import render_forecast_accuracy
        render_forecast_accuracy(st.session_state["test_results"])

    app = AppTest.from_function(_app_script)
    app.session_state["test_results"] = results
    app.run(timeout=20)
    assert not app.exception
    info_texts = [item.value for item in app.info]
    assert any("Holdout Demand Note: 1 of 2 evaluated SKUs had 0 actual demand" in text for text in info_texts)
    md_texts = [item.value for item in app.markdown]
    assert any("Active Mapped SKUs Evaluated" in text for text in md_texts)
