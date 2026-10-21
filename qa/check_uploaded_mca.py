"""Independent backend audit using the same raw stock workbook as browser QA."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from analytics_data import load_transactions
from analytics_pipeline import run_analytics_pipeline
from etl_config import InventoryConfig
from etl_inventory import load_current_inventory, validate_current_inventory, build_inventory_crosswalk
from forecasting_pipeline import run_forecasting_pipeline
from prescriptive_pipeline import build_sku_mapping_from_stock_upload, run_prescriptive_pipeline
from star_schema_db import read_runtime_star_schema


def main():
    transactions = load_transactions()
    dimension = read_runtime_star_schema(ROOT / ".artifacts/qa/full_seed.db")["dim_product"]
    config = InventoryConfig(stock_as_of=pd.Timestamp("2026-09-09"), stock_definition_confirmed=True)
    inventory = load_current_inventory(config)
    assert validate_current_inventory(inventory, config)["valid"]
    crosswalk = build_inventory_crosswalk(inventory, dimension, config)
    mapping, _ = build_sku_mapping_from_stock_upload(transactions, crosswalk,
        stock_as_of=config.stock_as_of, as_of="2026-10-12")
    forecast = run_forecasting_pipeline(transactions, mapping=mapping)
    result = run_prescriptive_pipeline(transactions, run_analytics_pipeline(transactions),
        forecast, crosswalk, as_of="2026-10-12")
    audit = result["mca_audit"]
    assert "Stock-Out Frequency" not in audit
    assert result["mca_results"].empty and not audit["MCA Eligible"].any()
    output = ROOT / "validation_outputs/five_criterion_mca"
    output.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output / "uploaded_stock_mca_audit.csv", index=False)
    summary = {"assessment_date": "2026-10-12", "stock_source": str(config.source_path.relative_to(ROOT)),
        "transaction_rows": len(transactions), "forecast_skus": len(audit),
        "scored_skus": len(result["mca_results"]),
        "risk_rows": len(result["risk_results"]), "recommendation_rows": len(result["recommendation_results"]),
        "status_counts": audit["MCA Status"].value_counts().to_dict(),
        "scope": "Raw uploaded workbook and isolated full-seed product dimension; distinct from governed catalog audit."}
    (output / "uploaded_stock_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
