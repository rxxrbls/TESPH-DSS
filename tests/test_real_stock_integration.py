"""Integration test verifying current stock processing and downstream pipeline with real raw_data."""

from datetime import date
from pathlib import Path
import openpyxl
import pandas as pd
import pytest

from etl_config import CURRENT_INVENTORY_SOURCE, FINAL_OUTPUT_DIR, InventoryConfig
from etl import load_final_table
from etl_inventory import load_current_inventory, validate_current_inventory, build_inventory_crosswalk
from active_inventory import build_active_mapping
from forecasting_pipeline import run_forecasting_pipeline
from prescriptive_pipeline import build_sku_mapping_from_stock_upload, run_prescriptive_pipeline
from analytics_pipeline import run_analytics_pipeline


def test_real_stock_raw_file_integration():
    """Verify that the raw Shopee current-stock file parses, maps, forecasts, and prescribes."""
    assert CURRENT_INVENTORY_SOURCE.is_file(), f"Missing {CURRENT_INVENTORY_SOURCE}"

    stock_as_of = date(2026, 9, 9)
    config = InventoryConfig(
        source_path=CURRENT_INVENTORY_SOURCE,
        stock_as_of=stock_as_of,
        stock_definition_confirmed=True,
    )
    # 1. Load inventory
    inventory = load_current_inventory(config)
    assert not inventory.empty
    assert len(inventory) == 1980

    # 2. Validate inventory
    validation = validate_current_inventory(inventory, config)
    assert validation["valid"] is True

    # 3. Build crosswalk
    dim_product = load_final_table("dim_product", FINAL_OUTPUT_DIR)
    crosswalk = build_inventory_crosswalk(inventory, dim_product, config)
    assert not crosswalk.empty

    # 4. Map active SKUs with confirmed date anchor
    txns = load_final_table("prepared_transactions", FINAL_OUTPUT_DIR)
    effective_as_of = pd.Timestamp(stock_as_of).normalize()
    mapping, audit = build_sku_mapping_from_stock_upload(
        txns,
        crosswalk,
        stock_as_of=stock_as_of,
        as_of=effective_as_of,
        max_stock_age_days=30,
    )
    active_skus = mapping.loc[mapping["active"], "SKU"].tolist()
    assert len(active_skus) == 65, f"Expected 65 active SKUs, got {len(active_skus)}"

    # 5. Demand Forecast
    forecasts = run_forecasting_pipeline(txns, mapping=mapping)
    forecast_output = forecasts.get("forecast_output")
    assert forecast_output is not None and not forecast_output.empty

    # 6. Prescriptive Pipeline
    analytics = run_analytics_pipeline(txns)
    prescriptive = run_prescriptive_pipeline(
        txns,
        analytics,
        forecasts,
        crosswalk,
        as_of=effective_as_of,
        max_stock_age_days=30,
    )
    assert "risk_results" in prescriptive
    assert "mca_results" in prescriptive
    assert "recommendation_results" in prescriptive

    risk = prescriptive["risk_results"]
    assert not risk.empty
    assert set(risk["Stock-Out Risk"].unique()).issubset({"Critical", "High", "Medium", "Low", "No Forecast Demand", "Insufficient Stock Data"})

    recs = prescriptive["recommendation_results"]
    assert not recs.empty
    assert "Target Stock Level" in recs.columns
    assert "Recommended Quantity" in recs.columns


def test_custom_sheet_name_fallback(tmp_path):
    """Verify that an inventory workbook with a non-default sheet name (e.g. Mass Update) loads seamlessly."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mass Update"
    headers = [
        "Product ID", "Product Name", "Variation ID", "Variation Name",
        "Parent SKU", "SKU", "Price", "Stock",
    ]
    # Row 1, 2 instruction; Row 3 headers; Row 4, 5, 6 instruction; Row 7 data
    ws.append(["Instructions"])
    ws.append(["More instructions"])
    ws.append(headers)
    ws.append(["Data begins row 7"])
    ws.append([""])
    ws.append([""])
    ws.append(["12345", "Test Product", "67890", "Red", "PARENT", "TEST-SKU", "150", "25"])
    test_path = tmp_path / "test_mass_update.xlsx"
    wb.save(test_path)
    wb.close()

    # Default config has sheet_name="Sheet1"
    config = InventoryConfig(source_path=test_path)
    result = load_current_inventory(config)
    assert len(result) == 1
    assert result.attrs["sheet_name"] == "Mass Update"
    assert result.iloc[0]["SKU"] == "TEST-SKU"
    assert result.iloc[0]["Stock"] == "25"
