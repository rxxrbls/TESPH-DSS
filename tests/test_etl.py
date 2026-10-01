from pathlib import Path

import pandas as pd
import pytest

from etl import (
    detect_exact_duplicates,
    detect_missing_values,
    extract_file,
    transform_transactions,
    validate_data_types,
    validate_required_columns,
)


def valid_frame():
    return pd.DataFrame({
        "Order ID": ["A-1", "A-2"],
        "Product Name": ["Widget", "Gadget"],
        "Variation Name": ["Blue", "Small"],
        "Quantity": [2, 1],
        "Order Creation Date": ["2024-01-02 10:00", "2024-01-03 11:00"],
        "SKU Reference No.": [pd.NA, "SKU-2"],
        "Service Fee": [-5, 3],
    })


def test_extract_valid_csv(tmp_path):
    path = tmp_path / "orders.csv"
    valid_frame().to_csv(path, index=False)
    assert extract_file(path).shape == (2, 7)


def test_extract_valid_xlsx_uses_orders_sheet(tmp_path):
    path = tmp_path / "orders.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"wrong": [1]}).to_excel(writer, sheet_name="Summary", index=False)
        valid_frame().to_excel(writer, sheet_name="orders", index=False)
    assert list(extract_file(path).columns) == list(valid_frame().columns)


def test_missing_required_column_has_clear_error():
    with pytest.raises(ValueError, match="Missing required column: Product Name"):
        validate_required_columns(valid_frame().drop(columns="Product Name"))


def test_exact_duplicates_detected_but_repeated_order_id_is_not_enough():
    frame = valid_frame()
    repeated_order = pd.concat([frame, frame.iloc[[0]].assign(**{"Product Name": "Different"})], ignore_index=True)
    assert not detect_exact_duplicates(repeated_order).any()
    exact = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert detect_exact_duplicates(exact).sum() == 2


def test_missing_values_detected_and_not_changed_to_zero():
    frame = valid_frame()
    missing = detect_missing_values(frame)
    assert ((missing["row"] == 0) & (missing["column"] == "SKU Reference No.")).any()
    assert pd.isna(frame.loc[0, "SKU Reference No."])


def test_invalid_date_and_numeric_values_are_flagged():
    frame = valid_frame()
    frame.loc[0, "Order Creation Date"] = "not-a-date"
    frame["Quantity"] = frame["Quantity"].astype("object")
    frame.loc[1, "Quantity"] = "many"
    report = validate_data_types(frame)
    assert not report["valid"]
    assert set(report["invalid_values"]["column"]) == {"Order Creation Date", "Quantity"}


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_empty_file_rejected(tmp_path, suffix):
    path = tmp_path / f"empty{suffix}"
    if suffix == ".csv":
        path.write_text("", encoding="utf-8")
    else:
        pd.DataFrame(columns=["Order ID"]).to_excel(path, sheet_name="orders", index=False)
    with pytest.raises(ValueError, match="empty|no data rows"):
        extract_file(path)


def test_valid_transformed_output_has_required_derived_fields():
    result = transform_transactions(valid_frame())
    expected = {"product_key", "standardized_product_name", "order_date", "order_year", "order_month", "year_month"}
    assert expected.issubset(result.columns)
    assert result[list(expected)].notna().all().all()


def test_blank_sku_does_not_fail_required_schema_validation():
    resolved = validate_required_columns(valid_frame())
    assert set(resolved) == {"Order ID", "Product Name", "Quantity", "Order Creation Date"}


def test_negative_financial_value_is_preserved_and_flagged():
    frame = valid_frame()
    report = validate_data_types(frame)
    assert report["valid"]
    assert report["negative_financial_values"].iloc[0]["value"] == -5
    transformed = transform_transactions(frame)
    assert transformed.loc[0, "Service Fee"] == -5
    assert bool(transformed.loc[0, "has_negative_financial_value"])
