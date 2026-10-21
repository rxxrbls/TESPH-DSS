"""Regression for the source identifier defects found in historical preparation."""
import pandas as pd
import pytest
from etl import extract_file, transform_transactions
from etl_config import SOURCE_COLUMNS
from final_etl_handoff import build_star_schema_tables


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_upload_preserves_numeric_and_internal_space_skus(tmp_path, extension):
    identifiers = ["0", "130244", "00130244", "BELOSNSCREEN-Set of 3pcs  Belo",
                   "TrashBag-Large  10pcs / Roll", "LICORISESERUM-1pc  Licorise S"]
    rows = []
    for i, sku in enumerate(identifiers):
        row = dict.fromkeys(SOURCE_COLUMNS, "")
        row.update({"Order ID": f"SOURCE-{i}", "Product Name": f"Identifier fixture {i}",
                    "Variation Name": "Default", "SKU Reference No.": sku,
                    "Order Status": "Completed", "Quantity": 1, "Returned quantity": 0,
                    "Original Price": 10, "Deal Price": 10,
                    "Order Creation Date": "2026-01-15 10:00:00"})
        rows.append(row)
    frame = pd.DataFrame(rows)
    path = tmp_path / f"source.{extension}"
    if extension == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_excel(path, sheet_name="orders", index=False)
    extracted = extract_file(path)
    extracted["source_file"] = path.name
    extracted["source_folder"] = "upload"
    transformed = transform_transactions(extracted)
    assert list(transformed["SKU Reference No."]) == identifiers
    tables = build_star_schema_tables(transformed)
    assert list(tables["prepared_transactions"]["SKU Reference No."]) == identifiers
    assert set(tables["dim_product"]["SKU"]) == set(identifiers)
