"""Isolated source-exact SKU restoration and full before/after pipeline comparison."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa.audit_sku_recovery import text, digest, preserve
from analytics_data import load_transactions
from analytics_pipeline import run_analytics_pipeline
from analytics_calculations import prepare_transactions
from etl_config import InventoryConfig
from etl_inventory import load_current_inventory, build_inventory_crosswalk
from star_schema_db import read_runtime_star_schema
from prescriptive_pipeline import build_sku_mapping_from_stock_upload, run_prescriptive_pipeline
from forecasting_pipeline import run_forecasting_pipeline
from three_criterion_mca import Coverage


def main():
    out = ROOT / "validation_outputs/sku_recovery"
    private = ROOT / ".artifacts/qa/sku_recovery"
    before_hashes = preserve()
    source_hash = digest(ROOT / "final_outputs/prepared_transactions.csv")
    tx = load_transactions()
    lineage = pd.read_csv(private / "row_lineage.csv", dtype=str, keep_default_na=False)
    review = pd.read_csv(private / "catalog_eligibility.csv", dtype=str, keep_default_na=False)
    conflicts = set(review.loc[review.Reason.eq("Historical/current SKU conflict"), "product_key"])
    literal_audit = private / "all_literal_differences.csv"
    if literal_audit.exists():
        conflicts |= set(pd.read_csv(literal_audit, dtype=str).product_key)
    targets = lineage.loc[lineage["SKU Reference No."].ne("") &
                          (lineage.sku_preserved.eq("False") | lineage.product_key.isin(conflicts))]
    # Retrieve literal seller identifiers, not numeric stripping or fuzzy matching.
    identities = ["Order ID", "Product Name", "Variation Name"]
    candidate = tx.copy()
    changes = []
    for (folder, filename), group in targets.groupby(["source_folder", "source_file"]):
        path = ROOT / "raw_data" / folder / filename
        with pd.ExcelFile(path, engine="openpyxl") as book:
            sheet = next((s for s in book.sheet_names if s.lower() == "orders"), book.sheet_names[0])
            raw = pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False)
        for column in identities:
            raw[column] = raw[column].map(text)
        original = raw.groupby(identities)["SKU Reference No."].agg(lambda s: set(s))
        for idx, row in group.iterrows():
            values = original.loc[tuple(row[c] for c in identities)]
            assert len(values) == 1, "Ambiguous source identity must not be restored"
            value = next(iter(values))
            assert value.strip(), "Never substitute a blank identifier"
            if str(candidate.loc[idx, "SKU Reference No."]) != value:
                changes.append({"product_key": row.product_key, "source_file": filename,
                                "before": candidate.loc[idx, "SKU Reference No."], "after": value})
                candidate.loc[idx, "SKU Reference No."] = value
    pd.DataFrame(changes).to_csv(out / "source_exact_changes.csv", index=False)
    # All other transaction fields and row ordering must be identical.
    pd.testing.assert_frame_equal(tx.drop(columns="SKU Reference No."),
                                  candidate.drop(columns="SKU Reference No."))
    candidate.to_csv(private / "source_exact_candidate.csv", index=False)
    dimension = read_runtime_star_schema(ROOT / ".artifacts/qa/full_seed.db")["dim_product"]
    updated_dim = dimension.copy()
    for key in {r["product_key"] for r in changes}:
        labels = sorted(set(candidate.loc[candidate.product_key.eq(key), "SKU Reference No."].dropna()))
        updated_dim.loc[updated_dim.product_key.eq(key), "SKU"] = " | ".join(labels)
    pd.testing.assert_frame_equal(dimension.drop(columns="SKU"), updated_dim.drop(columns="SKU"))
    config = InventoryConfig(stock_as_of=pd.Timestamp("2026-09-09"), stock_definition_confirmed=True)
    stock = load_current_inventory(config)
    with zipfile.ZipFile(ROOT.parent / "RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip") as archive:
        snapshot = pd.read_csv(archive.open(next(n for n in archive.namelist()
            if n.endswith("/prepared_return_refund_backend.csv"))), dtype=str, keep_default_na=False)
    coverage = Coverage("2020-05-22", "2026-04-24", "2020-05-01", "2026-04-24",
                        "2026-10-15", "2026-10-16", established=True)
    outputs = {}
    summary = {"changed_transaction_references": len(changes),
               "changed_product_keys": len({r["product_key"] for r in changes}),
               "source_transaction_sha256": source_hash}
    for label, records, dim in (("before", tx, dimension), ("after", candidate, updated_dim)):
        print(f"Running {label} unchanged analytics, forecasting and MCA pipelines", flush=True)
        cross = build_inventory_crosswalk(stock, dim, config)
        mapping, reviewed = build_sku_mapping_from_stock_upload(records, cross,
            stock_as_of=config.stock_as_of, as_of="2026-10-20")
        keys = set(mapping.loc[mapping.SKU.notna(), "product_key"])
        forecasts = run_forecasting_pipeline(records, mapping=mapping)
        analytics = run_analytics_pipeline(records)
        results = run_prescriptive_pipeline(records, analytics, forecasts, cross,
            as_of="2026-10-20", mca_return_snapshot=snapshot, mca_coverage=coverage,
            mca_period_start=coverage.order_start, mca_period_end=coverage.order_end)
        prepared = prepare_transactions(records)
        eligible = prepared.loc[prepared["Product Key"].isin(keys)]
        summary[label] = {
            "accepted_catalog_skus": len(keys),
            "transaction_rows_in_accepted_mapping": len(eligible),
            "gross_demand_units_in_accepted_mapping": float(eligible["Gross Demand"].sum()),
            "forecast_skus": int(forecasts["best_methods"].SKU.nunique()),
            "forecast_rows": len(forecasts["forecast_output"]),
            "nonzero_forecast_rows": int(forecasts["forecast_output"].Forecast.ne(0).sum()),
            "return_lines_in_accepted_mapping": int(snapshot.product_key.isin(keys).sum()),
            "refunded_lines_in_accepted_mapping": int((snapshot.product_key.isin(keys)
                & snapshot["Return / Refund Status"].eq("Request Refunded")).sum()),
            "mca_scores": len(results["mca_results"]),
            "mca_readiness": results["mca_audit"]["MCA Status"].value_counts().to_dict(),
            "catalog_exclusion_reasons": reviewed.Reason.value_counts().to_dict(),
        }
        for name in ("mca_audit", "mca_results", "mca_sensitivity"):
            if name in results:
                results[name].to_csv(out / f"{label}_{name}.csv", index=False)
        forecasts["forecast_output"].to_csv(out / f"{label}_forecasts.csv", index=False)
        mapping.to_csv(private / f"{label}_mapping.csv", index=False)
        reviewed.to_csv(private / f"{label}_catalog_review.csv", index=False)
        outputs[label] = (keys, forecasts, results)
    common_skus = set(outputs["before"][1]["best_methods"].SKU)
    b = outputs["before"][1]["forecast_output"]
    a = outputs["after"][1]["forecast_output"]
    pd.testing.assert_frame_equal(b.reset_index(drop=True),
        a.loc[a.SKU.isin(common_skus)].reset_index(drop=True))
    summary["existing_sku_forecasts_unchanged"] = True
    summary["new_catalog_product_keys"] = sorted(outputs["after"][0] - outputs["before"][0])
    summary["working_files_unchanged"] = all(digest(ROOT / p) == v for p, v in before_hashes.items())
    summary["source_unchanged"] = digest(ROOT / "final_outputs/prepared_transactions.csv") == source_hash
    assert summary["source_unchanged"] and summary["working_files_unchanged"]
    (out / "restoration_comparison.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
