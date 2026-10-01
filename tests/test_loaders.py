import csv

import pandas as pd
import pytest

from etl import load_final_table, load_prepared_transactions, load_star_schema
from etl_config import FINAL_SCHEMAS


def write_table(tmp_path, name, overrides=None, rename=None):
    row = {column: "" for column in FINAL_SCHEMAS[name]}
    row.update(overrides or {})
    frame = pd.DataFrame([row]).rename(columns=rename or {})
    path = tmp_path / f"{name}.csv"
    frame.to_csv(path, index=False)
    return path


def test_prepared_loader_preserves_exact_identifiers_and_missing_sku(tmp_path):
    path = write_table(tmp_path, "prepared_transactions", {
        "Order ID": "00012", "SKU Reference No.": "NA", "Quantity": 3,
        "Returned quantity": 1, "Parent SKU Reference No.": "",
    })
    before = path.read_bytes()
    frame = load_prepared_transactions(tmp_path)
    assert frame.loc[0, "Order ID"] == "00012"
    assert frame.loc[0, "SKU Reference No."] == "NA"
    assert pd.isna(frame.loc[0, "Parent SKU Reference No."])
    assert frame.loc[0, "Returned quantity"] == 1
    assert "Order_ID" not in frame
    assert "product_id" not in frame
    assert path.read_bytes() == before


def test_star_schema_loader_uses_each_tables_own_contract(tmp_path):
    names = ("fact_sales", "dim_product", "dim_date", "dim_order", "dim_shipping", "dim_payment")
    for name in names:
        overrides = {"SKU": "000042"} if name == "dim_product" else {}
        write_table(tmp_path, name, overrides)
    files_before = {p.name: p.read_bytes() for p in tmp_path.glob("*.csv")}
    tables = load_star_schema(tmp_path)
    assert set(tables) == set(names)
    assert tables["dim_product"].loc[0, "SKU"] == "000042"
    assert "Order ID" in tables["fact_sales"]
    assert "Order ID" in tables["dim_order"]
    for name in ("dim_product", "dim_date", "dim_shipping", "dim_payment"):
        assert "Order ID" not in tables[name]
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.csv")} == files_before


@pytest.mark.parametrize("table,old,new", [
    ("prepared_transactions", "Order ID", "Order_ID"),
    ("fact_sales", "Order ID", "Order_ID"),
    ("fact_sales", "Returned quantity", "Returned Quantity"),
    ("prepared_transactions", "SKU Reference No.", "SKU"),
    ("dim_product", "SKU", "SKU Reference No."),
    ("dim_product", "standardized Product Name", "standardized_product_name"),
])
def test_renamed_frozen_fields_fail_with_clear_error(tmp_path, table, old, new):
    write_table(tmp_path, table, rename={old: new})
    with pytest.raises(ValueError, match="Invalid .* schema") as error:
        load_final_table(table, tmp_path)
    assert old in str(error.value)
    assert new in str(error.value)


@pytest.mark.parametrize("table", ["dim_product", "dim_date", "dim_shipping", "dim_payment"])
def test_order_id_in_unrelated_dimension_is_rejected(tmp_path, table):
    write_table(tmp_path, table, {"Order ID": "A-1"})
    with pytest.raises(ValueError, match="unexpected=.*Order ID"):
        load_final_table(table, tmp_path)


def test_duplicate_header_is_rejected_before_pandas_renames_it(tmp_path):
    path = tmp_path / "dim_product.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(list(FINAL_SCHEMAS["dim_product"]) + ["SKU"])
    with pytest.raises(ValueError, match="duplicate=.*SKU"):
        load_final_table("dim_product", tmp_path)


def test_missing_file_and_unknown_table_are_clear_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prepared_transactions(tmp_path)
    with pytest.raises(ValueError, match="Unknown final table"):
        load_final_table("arbitrary-table", tmp_path)


def test_empty_file_has_schema_error(tmp_path):
    (tmp_path / "prepared_transactions.csv").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="missing="):
        load_prepared_transactions(tmp_path)
