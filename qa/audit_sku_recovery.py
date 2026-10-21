"""Read-only raw-SKU lineage audit and isolated catalog-backed recovery trial."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import sys
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from etl import standardize_text_value
from etl_config import InventoryConfig
from etl_inventory import load_current_inventory, build_inventory_crosswalk
from star_schema_db import read_runtime_star_schema
from analytics_data import load_transactions
from prescriptive_pipeline import build_sku_mapping_from_stock_upload

OUT = ROOT / "validation_outputs/sku_recovery"
PRIVATE = ROOT / ".artifacts/qa/sku_recovery"
KEY = ["Order ID", "Product Name", "Variation Name"]
SKU = "SKU Reference No."


def text(value):
    result = standardize_text_value(value)
    return "" if pd.isna(result) else str(result)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve():
    files = list(ROOT.glob("*.py"))
    for folder in ("analytics", "pages", "src", "utils", "tests", "qa", "docs"):
        files.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and p.suffix in {".py", ".md", ".json", ".csv"} and "__pycache__" not in p.parts)
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in sorted(set(files))}
    snapshot = PRIVATE / "working_source_before_investigation.zip"
    if snapshot.exists():
        # Preserve the first checkpoint across reruns.
        with zipfile.ZipFile(snapshot) as archive:
            assert archive.testzip() is None
    else:
        with zipfile.ZipFile(snapshot, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename in hashes:
                archive.write(ROOT / filename, filename)
            archive.writestr("source_manifest.json", json.dumps(hashes, indent=2))
    return hashes


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    before = preserve()
    source = ROOT / "final_outputs/prepared_transactions.csv"
    source_hash = digest(source)
    columns = [*KEY, SKU, "Parent SKU Reference No.", "source_file", "source_folder", "product_key"]
    prepared = pd.read_csv(source, usecols=columns, dtype=str, keep_default_na=False)
    for c in columns:
        prepared[c] = prepared[c].map(text)
    paths = sorted(p for p in (ROOT / "raw_data").glob("*/*.xlsx") if p.parent.name.isdigit())
    raw_parts, inventory = [], []
    cache = PRIVATE / "original_identifier_rows.csv"
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    cache_manifest = PRIVATE / "original_file_hashes.json"
    if cache.exists() and cache_manifest.exists() and json.loads(cache_manifest.read_text()) == source_hashes:
        raw = pd.read_csv(cache, dtype=str, keep_default_na=False)
        inventory = json.loads((PRIVATE / "raw_inventory.json").read_text())
    else:
        for index, path in enumerate(paths):
            with pd.ExcelFile(path, engine="openpyxl") as book:
                sheet = next((s for s in book.sheet_names if s.lower() == "orders"), book.sheet_names[0])
                frame = pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False)
            ids = [c for c in frame if any(word in c.lower() for word in ("sku", "product id", "variation id", "item id", "model id")) and "weight" not in c.lower()]
            entry = {"file": str(path.relative_to(ROOT)), "rows": len(frame), "identifier_columns": ids,
                     "nonblank": {c: int(frame[c].map(text).ne("").sum()) for c in ids}}
            inventory.append(entry)
            if len(frame):
                missing = set(KEY + [SKU]) - set(frame)
                if missing:
                    raise ValueError(f"{path.name}: missing identity fields {missing}")
                part = frame.reindex(columns=[*KEY, SKU, "Parent SKU Reference No."]).fillna("")
                part["source_file"] = path.name
                part["source_folder"] = path.parent.name
                for c in part:
                    part[c] = part[c].map(text)
                raw_parts.append(part)
            if (index + 1) % 12 == 0:
                print(f"Inspected {index + 1}/{len(paths)} original workbooks", flush=True)
        raw = pd.concat(raw_parts, ignore_index=True)
        raw.to_csv(cache, index=False)
        cache_manifest.write_text(json.dumps(source_hashes, indent=2), encoding="utf-8")
        (PRIVATE / "raw_inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (OUT / "raw_file_inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    # Set comparisons avoid multiplying repeated item lines. Source filename is
    # retained: another month cannot be used as proof of a processing loss.
    lineage_key = ["source_file", *KEY]
    grouped = raw.groupby(lineage_key, dropna=False)[SKU].agg(lambda s: sorted(set(s)))
    lineage = prepared.merge(grouped.rename("raw_sku_values"), on=lineage_key, how="left", validate="many_to_one")
    lineage["source_matched"] = lineage.raw_sku_values.map(lambda x: isinstance(x, list))
    lineage["sku_preserved"] = [isinstance(values, list) and value in values
                                for value, values in zip(lineage[SKU], lineage.raw_sku_values)]
    lineage["raw_has_nonblank"] = lineage.raw_sku_values.map(lambda values: isinstance(values, list) and any(values))
    lineage["possible_loss"] = lineage[SKU].eq("") & lineage.raw_has_nonblank
    # A blank original and a nonblank original for the same identity is ambiguous,
    # not proof that processing lost the identifier.
    lineage["confirmed_nonblank_to_blank"] = lineage["possible_loss"] & lineage.raw_sku_values.map(
        lambda values: isinstance(values, list) and "" not in values)
    lineage.to_csv(PRIVATE / "row_lineage.csv", index=False)

    tx = load_transactions()
    cfg = InventoryConfig(stock_as_of=pd.Timestamp("2026-09-09"), stock_definition_confirmed=True)
    stock = load_current_inventory(cfg)
    dimension = read_runtime_star_schema(ROOT / ".artifacts/qa/full_seed.db")["dim_product"]
    cross = build_inventory_crosswalk(stock, dimension, cfg)
    mapping, review = build_sku_mapping_from_stock_upload(tx, cross, stock_as_of=cfg.stock_as_of, as_of="2026-10-20")
    accepted = mapping.loc[mapping.SKU.notna(), ["product_key", "SKU"]]
    cross.to_csv(PRIVATE / "catalog_crosswalk.csv", index=False)
    review.to_csv(PRIVATE / "catalog_eligibility.csv", index=False)

    # Only existing, already accepted catalog SKUs can fill blank historical
    # references for the same governed product key. No new identifiers or
    # conflict overrides are introduced.
    sku_by_key = accepted.set_index("product_key").SKU
    candidate = prepared.product_key.map(sku_by_key)
    blank = prepared[SKU].eq("")
    recoverable = blank & candidate.notna()
    recovered = tx.copy()
    recovered.loc[recoverable, SKU] = candidate.loc[recoverable]
    recovery_rows = prepared.loc[recoverable, ["product_key", "source_file"]].copy()
    recovery_rows["Existing Catalog SKU"] = candidate.loc[recoverable]
    recovery_rows.groupby(["product_key", "Existing Catalog SKU"], as_index=False).size().to_csv(
        OUT / "safe_existing_mapping_fill_counts.csv", index=False)
    recovered.to_csv(PRIVATE / "candidate_transactions.csv", index=False)
    after_mapping, after_review = build_sku_mapping_from_stock_upload(
        recovered, cross, stock_as_of=cfg.stock_as_of, as_of="2026-10-20")
    pd.testing.assert_frame_equal(mapping, after_mapping)
    with zipfile.ZipFile(ROOT.parent / "RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip") as archive:
        rr = pd.read_csv(archive.open(next(n for n in archive.namelist() if n.endswith("/prepared_return_refund_backend.csv"))),
                         dtype=str, keep_default_na=False)
    keys = set(accepted.product_key)
    raw_ids = sorted({c for row in inventory for c in row["identifier_columns"]})
    summary = {
        "original_workbooks": len(paths), "raw_rows": len(raw), "prepared_rows": len(prepared),
        "raw_blank_sku_rows": int(raw[SKU].eq("").sum()),
        "prepared_blank_sku_rows": int(blank.sum()),
        "unmatched_prepared_identities": int((~lineage.source_matched).sum()),
        "prepared_sku_not_found_in_original_identity": int((~lineage.sku_preserved).sum()),
        "confirmed_nonblank_to_blank": int(lineage.confirmed_nonblank_to_blank.sum()),
        "blank_prepared_with_some_nonblank_original_identity": int(lineage.possible_loss.sum()),
        "original_identifier_columns": raw_ids,
        "source_file_sets_match": set(prepared.source_file) == set(raw.source_file),
        "original_nonblank_parent_sku_rows": int(raw["Parent SKU Reference No."].ne("").sum()),
        "stock_rows": len(stock), "stock_missing_sku": int(stock.SKU.map(text).eq("").sum()),
        "catalog_eligibility_reasons": review.Reason.value_counts().to_dict(),
        "safe_blank_reference_fills": int(recoverable.sum()),
        "products_with_safe_reference_fills": int(prepared.loc[recoverable, "product_key"].nunique()),
        "accepted_catalog_skus_before": len(accepted),
        "accepted_catalog_skus_after": int(after_mapping.SKU.notna().sum()),
        "accepted_mapping_unchanged": True,
        "return_lines_in_accepted_mapping_before": int(rr.product_key.isin(keys).sum()),
        "return_lines_in_accepted_mapping_after": int(rr.product_key.isin(set(after_mapping.loc[after_mapping.SKU.notna(),"product_key"])).sum()),
        "source_transaction_sha256": source_hash,
        "source_unchanged": digest(source) == source_hash,
        "working_files_unchanged": all(digest(ROOT / filename) == checksum for filename, checksum in before.items()),
    }
    assert summary["source_unchanged"] and summary["working_files_unchanged"]
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
