"""Actual-data provisional assessment, isolated from the application's runtime."""
from dataclasses import asdict
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import zipfile

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
from three_criterion_mca import Coverage, rank_scenarios
from return_refund_store import refresh_batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=ROOT.parent / "RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip")
    args = parser.parse_args()
    out = ROOT / "validation_outputs/three_criterion_mca"
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with zipfile.ZipFile(args.archive) as archive:
        name = next(n for n in archive.namelist() if n.endswith("/prepared_return_refund_backend.csv"))
        snapshot = pd.read_csv(archive.open(name), dtype=str, keep_default_na=False)
    transactions = load_transactions()
    dimension = read_runtime_star_schema(ROOT / ".artifacts/qa/full_seed.db")["dim_product"]
    config = InventoryConfig(stock_as_of=pd.Timestamp("2026-09-09"), stock_definition_confirmed=True)
    inventory = load_current_inventory(config)
    assert validate_current_inventory(inventory, config)["valid"]
    crosswalk = build_inventory_crosswalk(inventory, dimension, config)
    mapping, _ = build_sku_mapping_from_stock_upload(transactions, crosswalk,
        stock_as_of=config.stock_as_of, as_of="2026-10-20")
    forecasts = run_forecasting_pipeline(transactions, mapping=mapping)
    analytics = run_analytics_pipeline(transactions)
    coverage = Coverage("2020-05-22", "2026-04-24", "2020-05-01", "2026-04-24",
                        "2026-10-15", "2026-10-16", established=True)
    def calculate(records, policy):
        return run_prescriptive_pipeline(transactions, analytics, forecasts, crosswalk,
            as_of="2026-10-20", mca_return_snapshot=records, mca_coverage=Coverage(**policy),
            mca_period_start=coverage.order_start, mca_period_end=coverage.order_end)
    results = refresh_batch(ROOT / ".artifacts/qa/three_criterion_review.db",
        batch_type="return_refund", snapshot=snapshot, coverage=coverage, calculate=calculate)
    scenarios, comparison, summary = rank_scenarios(results["mca_audit"])
    for name, frame in results.items():
        # Request-line audit contains business records: keep it in private artifacts.
        if name == "return_request_review":
            frame.to_csv(ROOT / ".artifacts/qa/three_criterion_request_review.csv", index=False)
        else:
            frame.to_csv(out / (name + ".csv"), index=False)
    for name, frame in scenarios.items():
        frame.to_csv(out / (name + ".csv"), index=False)
    comparison.to_csv(out / "sensitivity.csv", index=False)
    review = results["return_request_review"]
    summary.update({
        "coverage": asdict(coverage), "transaction_rows": len(transactions),
        "return_request_lines": len(snapshot),
        "review_decisions": review["Review Decision"].value_counts().to_dict(),
        "review_reasons": review["Review Reason"].value_counts().to_dict(),
        "readiness": results["mca_audit"]["MCA Status"].value_counts().to_dict(),
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "elapsed_seconds": time.perf_counter() - started,
        "limitation": "Selected request dates through April 24 only; not lifetime returns. October export requests are not a simultaneous source update cutoff.",
    })
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
