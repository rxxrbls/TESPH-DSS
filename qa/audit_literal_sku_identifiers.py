"""Confirm literal source identifiers across every workbook with nonblank SKUs."""
from pathlib import Path
import json
import sys
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa.audit_sku_recovery import text


def main():
    private = ROOT / ".artifacts/qa/sku_recovery"
    cache = pd.read_csv(private / "original_identifier_rows.csv", dtype=str, keep_default_na=False)
    prepared = pd.read_csv(private / "row_lineage.csv", dtype=str, keep_default_na=False)
    selected = cache.loc[cache["SKU Reference No."].ne("")]
    parts = []
    files = selected[["source_folder", "source_file"]].drop_duplicates()
    columns = ["Order ID", "Product Name", "Variation Name", "SKU Reference No."]
    for i, (folder, filename) in enumerate(files.itertuples(index=False, name=None)):
        with pd.ExcelFile(ROOT / "raw_data" / folder / filename, engine="openpyxl") as book:
            sheet = next((s for s in book.sheet_names if s.lower() == "orders"), book.sheet_names[0])
            raw = pd.read_excel(book, sheet_name=sheet, usecols=columns, dtype=str, keep_default_na=False)
        raw = raw.loc[raw["SKU Reference No."].map(text).ne("")].copy()
        for col in columns[:-1]:
            raw[col] = raw[col].map(text)
        raw["source_file"] = filename
        parts.append(raw)
        if (i + 1) % 12 == 0:
            print(f"Literal identifier check: {i + 1}/{len(files)} workbooks", flush=True)
    raw = pd.concat(parts, ignore_index=True)
    raw.to_csv(private / "literal_nonblank_source_identifiers.csv", index=False)
    keys = ["source_file", *columns[:-1]]
    original = raw.groupby(keys)["SKU Reference No."].agg(lambda x: sorted(set(x)))
    matched = prepared.loc[prepared["SKU Reference No."].ne("")].merge(
        original.rename("literal_skus"), on=keys, how="left", validate="many_to_one")
    assert matched.literal_skus.map(lambda x: isinstance(x, list)).all()
    changed = matched.loc[[sku not in values for sku, values
                          in zip(matched["SKU Reference No."], matched.literal_skus)]].copy()
    changed.to_csv(private / "all_literal_differences.csv", index=False)
    result = {
        "workbooks_with_nonblank_skus": len(files), "literal_nonblank_source_rows": len(raw),
        "prepared_nonblank_sku_rows": len(matched), "literal_differences": len(changed),
        "differences_by_prepared_sku": changed["SKU Reference No."].value_counts().to_dict(),
        "ambiguous_original_identifiers": int(matched.literal_skus.map(len).gt(1).sum()),
    }
    known_path = ROOT / "validation_outputs/sku_recovery/source_exact_changes.csv"
    known = (pd.read_csv(known_path, dtype=str) if known_path.exists()
             else pd.DataFrame(columns=["product_key"]))
    result["restored_in_latest_trial"] = len(known)
    result["additional_differences_to_test"] = len(changed) - len(known)
    assert set(known.product_key).issubset(set(changed.product_key))
    (ROOT / "validation_outputs/sku_recovery/literal_identifier_audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
