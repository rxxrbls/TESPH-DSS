from dataclasses import replace
from datetime import date

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest
from openpyxl import Workbook

from etl_config import INVENTORY_COLUMNS, InventoryConfig
from etl_inventory import build_inventory_crosswalk, load_current_inventory, validate_current_inventory


@pytest.fixture
def inventory():
    return pd.DataFrame([
        ["101", "Widget", "1001", "Blue", "", "SKU-1", 20, 5],
        ["102", "Gadget", "1002", "Small", None, None, 30, 0],
    ], columns=INVENTORY_COLUMNS, dtype=object)


@pytest.fixture
def historical():
    return pd.DataFrame({
        "product_key": ["historical-key-1", "historical-key-2"],
        "original Product Name": ["Widget", "Gadget"],
        "original Variation Name": ["Blue", "Small"],
        "final_base_product_name": ["Reviewed Widget", "Reviewed Gadget"],
        "standardized Product Name": ["widget", "gadget"],
        "standardized Variation Name": ["blue", "small"],
        "Parent SKU": [None, None], "SKU": ["SKU-1", "SKU-2"],
        "final_category": ["Category A", "Category B"],
    }, dtype=object)


def write_inventory(tmp_path, frame, header_row=3, data_start_row=7, sheet_name="Sheet1"):
    path = tmp_path / "inventory.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for row in range(1, data_start_row):
        sheet.append(list(frame.columns) if row == header_row else ["template instruction"])
    for row in frame.itertuples(index=False, name=None):
        sheet.append(list(row))
    workbook.save(path)
    workbook.close()
    return InventoryConfig(path, sheet_name, header_row, data_start_row)


def test_workbook_parsing_skips_metadata_and_instructions(tmp_path, inventory):
    inventory.loc[0, "Product ID"] = "000101"
    inventory.loc[0, "SKU"] = "NA"
    inventory.loc[0, "Stock"] = "0005"
    inventory["Fail Reason"] = ""
    config = write_inventory(tmp_path, inventory)
    original_bytes = config.source_path.read_bytes()
    result = load_current_inventory(config)
    assert len(result) == 2
    assert result.attrs["source_rows"] == (7, 8)
    assert result.loc[0, "Product ID"] == "000101"
    assert result.loc[0, "SKU"] == "NA"
    assert result.loc[0, "Stock"] == "0005"
    assert pd.isna(result.loc[1, "SKU"])
    assert "Fail Reason" in result
    assert config.source_path.read_bytes() == original_bytes


def test_configurable_sheet_and_row_layout(tmp_path, inventory):
    config = write_inventory(tmp_path, inventory, header_row=2, data_start_row=5, sheet_name="Client stock")
    assert load_current_inventory(config).attrs["source_rows"] == (5, 6)
    with pytest.raises(ValueError, match="sheet not found"):
        load_current_inventory(replace(config, sheet_name="Wrong"))


def test_stale_excel_dimension_does_not_truncate_rows(tmp_path, inventory):
    from zipfile import ZipFile
    import re

    config = write_inventory(tmp_path, inventory)
    stale = tmp_path / "stale_dimension.xlsx"
    with ZipFile(config.source_path) as source, ZipFile(stale, "w") as target:
        for entry in source.infolist():
            data = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1"', data)
            target.writestr(entry, data)
    assert len(load_current_inventory(replace(config, source_path=stale))) == 2


def test_client_invalid_frozen_pane_is_ignored_without_changing_source(tmp_path, inventory):
    from zipfile import ZipFile

    config = write_inventory(tmp_path, inventory)
    client_layout = tmp_path / "client_layout.xlsx"
    with ZipFile(config.source_path) as source, ZipFile(client_layout, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(
                    b'<sheetView workbookViewId="0">',
                    b'<sheetView workbookViewId="0"><pane activePane="bottom_left" '
                    b'state="frozen" topLeftCell="A5" ySplit="4"/>',
                )
                assert b'activePane="bottom_left"' in content
            target.writestr(entry, content)
    before = client_layout.read_bytes()
    result = load_current_inventory(replace(config, source_path=client_layout))
    assert len(result) == 2
    assert result["Stock"].tolist() == [5, 0]
    assert client_layout.read_bytes() == before


@pytest.mark.parametrize("column", INVENTORY_COLUMNS)
def test_inventory_required_columns_are_explicit(inventory, column):
    with pytest.raises(ValueError, match="Invalid inventory schema"):
        validate_current_inventory(inventory.drop(columns=column))


def test_missing_or_duplicate_workbook_headers_rejected(tmp_path, inventory):
    missing = write_inventory(tmp_path, inventory.rename(columns={"Stock": "Available_Stock"}))
    with pytest.raises(ValueError, match="Stock"):
        load_current_inventory(missing)
    duplicate = pd.concat([inventory, inventory[["SKU"]]], axis=1)
    with pytest.raises(ValueError, match="duplicate"):
        load_current_inventory(write_inventory(tmp_path, duplicate))


def test_empty_workbook_data_rejected(tmp_path, inventory):
    with pytest.raises(ValueError, match="no data rows"):
        load_current_inventory(write_inventory(tmp_path, inventory.iloc[:0]))


@pytest.mark.parametrize("sku", [None, "", "  ", pd.NA])
def test_missing_sku_is_preserved_and_is_not_an_error(inventory, sku):
    inventory.loc[0, "SKU"] = sku
    before = inventory.copy(deep=True)
    report = validate_current_inventory(inventory)
    assert report["valid"]
    assert report["row_checks"].loc[0, "missing_sku"]
    assert_frame_equal(inventory, before)


@pytest.mark.parametrize("value,issue", [
    (None, "missing_stock"), ("", "missing_stock"), ("  ", "missing_stock"),
    (float("nan"), "missing_stock"), ("many", "invalid_stock"),
    ("=1+2", "invalid_stock"), (float("inf"), "invalid_stock"),
    ("NaN", "invalid_stock"), (True, "invalid_stock"),
    (-1, "negative_stock"), ("-5", "negative_stock"), (1.5, "fractional_stock"),
])
def test_stock_problems_are_reported_without_replacement(inventory, historical, value, issue):
    inventory.loc[0, "Stock"] = value
    before = inventory.copy(deep=True)
    report = validate_current_inventory(inventory)
    assert not report["valid"]
    assert report["row_checks"].loc[0, "stock_issue"] == issue
    result = build_inventory_crosswalk(inventory, historical)
    assert not result.loc[0, "stock_valid"]
    assert result.loc[0, "mapping_review_required"]
    assert pd.isna(result.loc[0, "product_key"])
    assert_frame_equal(result[list(inventory.columns)], before)
    assert_frame_equal(inventory, before)


@pytest.mark.parametrize("value", [0, "0", 5, "0005", 200000])
def test_valid_stock_preserved_without_arbitrary_threshold(inventory, value):
    inventory.loc[0, "Stock"] = value
    assert validate_current_inventory(inventory)["valid"]
    assert inventory.loc[0, "Stock"] == value


@pytest.mark.parametrize("field", ["Product ID", "Variation ID"])
@pytest.mark.parametrize("value", [None, "", "abc", -1, 0, 2.5, True])
def test_invalid_identifiers_are_reported(inventory, field, value):
    inventory.loc[0, field] = value
    report = validate_current_inventory(inventory)
    assert not report["valid"]
    assert field in report["row_checks"].loc[0, "errors"]


def test_duplicate_listing_variation_ids_are_not_silently_dropped(inventory, historical):
    inventory.loc[1, ["Product ID", "Variation ID"]] = ["101", "1001"]
    result = build_inventory_crosswalk(inventory, historical)
    assert len(result) == 2
    assert result["product_key"].isna().all()
    assert result["review_reasons"].str.contains("duplicate_product_variation_id").all()


def test_exact_sku_priority_preserves_historical_key_and_inputs(inventory, historical):
    inventory.loc[0, "Product Name"] = "Renamed client listing"
    before_inventory, before_history = inventory.copy(deep=True), historical.copy(deep=True)
    result = build_inventory_crosswalk(inventory, historical)
    assert result.loc[0, "product_key"] == "historical-key-1"
    assert result.loc[0, "match_method"] == "exact_sku"
    assert result.loc[0, "match_status"] == "candidate"
    assert not result.loc[0, "mapping_review_required"]
    assert "product_id" not in result
    assert_frame_equal(result[list(inventory.columns)], before_inventory)
    assert_frame_equal(inventory, before_inventory)
    assert_frame_equal(historical, before_history)


def test_name_variation_fallback_uses_historical_normalization(inventory, historical):
    inventory.loc[1, "Product Name"] = "  ∩╝º∩╝í∩╝ñ∩╝º∩╝Ñ∩╝┤\t "
    inventory.loc[1, "Variation Name"] = " SMALL "
    result = build_inventory_crosswalk(inventory, historical)
    assert result.loc[1, "product_key"] == "historical-key-2"
    assert result.loc[1, "match_method"] == "normalized_name_variation"
    assert pd.isna(result.loc[1, "SKU"])


def test_sku_matching_is_exact_and_case_sensitive(inventory, historical):
    inventory.loc[0, "SKU"] = "sku-1"
    inventory.loc[0, "Product Name"] = "No name match"
    result = build_inventory_crosswalk(inventory, historical)
    assert result.loc[0, "match_status"] == "unmatched"


def test_reused_sku_keeps_each_stock_row_for_review(inventory, historical):
    inventory.loc[1, "SKU"] = "SKU-1"
    result = build_inventory_crosswalk(inventory, historical)
    assert len(result) == 2
    assert result["Stock"].tolist() == [5, 0]
    assert result["reused_sku"].all()
    assert result["mapping_review_required"].all()
    assert result["product_key"].isna().all()
    assert validate_current_inventory(inventory)["valid"]


def test_duplicate_historical_sku_is_ambiguous_even_with_name_candidate(inventory, historical):
    historical.loc[1, "SKU"] = "SKU-1"
    result = build_inventory_crosswalk(inventory, historical)
    assert result.loc[0, "match_method"] == "exact_sku"
    assert result.loc[0, "match_status"] == "review_required"
    assert pd.isna(result.loc[0, "product_key"])
    assert result.loc[0, "candidate_product_keys"] == "historical-key-1 | historical-key-2"


def test_conflicting_sku_and_name_evidence_requires_review(inventory, historical):
    inventory.loc[0, "SKU"] = "SKU-2"
    result = build_inventory_crosswalk(inventory, historical)
    assert "sku_name_conflict" in result.loc[0, "review_reasons"]
    assert pd.isna(result.loc[0, "product_key"])


def test_multi_value_historical_sku_is_review_only(inventory, historical):
    inventory.loc[0, "SKU"] = "0"
    historical.loc[:, "SKU"] = "0 | 0.0"
    result = build_inventory_crosswalk(inventory, historical)
    assert result.loc[0, "match_method"] == "historical_sku_alias_review"
    assert "historical_multi_value_sku" in result.loc[0, "review_reasons"]
    assert pd.isna(result.loc[0, "product_key"])


def test_multiple_historical_name_targets_require_review(inventory, historical):
    historical.loc[0, ["standardized Product Name", "standardized Variation Name"]] = ["gadget", "small"]
    result = build_inventory_crosswalk(inventory, historical)
    assert result.loc[1, "match_status"] == "review_required"
    assert pd.isna(result.loc[1, "product_key"])


def test_repeated_current_name_pairs_are_not_aggregated(inventory, historical):
    inventory.loc[0, ["Product Name", "Variation Name", "SKU"]] = ["Gadget", "Small", None]
    result = build_inventory_crosswalk(inventory, historical)
    assert len(result) == 2
    assert result["review_reasons"].str.contains("repeated_current_name_pair").all()
    assert result["product_key"].isna().all()


def test_unmatched_is_review_not_an_invalid_source(inventory, historical):
    inventory.loc[1, "Product Name"] = "New product without history"
    result = build_inventory_crosswalk(inventory, historical)
    assert validate_current_inventory(inventory)["valid"]
    assert result.loc[1, "match_status"] == "unmatched"
    assert result.loc[1, "review_required"]
    assert pd.isna(result.loc[1, "product_key"])
    assert result.loc[1, "Stock"] == 0


def test_stock_as_of_is_unavailable_unless_explicitly_supplied(inventory, historical):
    config = InventoryConfig()
    report = validate_current_inventory(inventory, config)
    result = build_inventory_crosswalk(inventory, historical, config)
    assert report["stock_as_of"] is None
    assert result["stock_as_of"].isna().all()
    assert (result["stock_as_of_status"] == "pending_confirmation").all()
    supplied = replace(config, stock_as_of=date(2026, 1, 2))  # Synthetic test value only.
    confirmed = build_inventory_crosswalk(inventory, historical, supplied)
    assert confirmed["stock_as_of"].tolist() == [date(2026, 1, 2)] * 2
    assert (confirmed["stock_as_of_status"] == "provided").all()
    assert (confirmed["stock_definition_status"] == "pending_client_confirmation").all()
    stock_confirmed = replace(config, stock_as_of=date(2026, 1, 2), stock_definition_confirmed=True)
    confirmed_semantics = build_inventory_crosswalk(inventory, historical, stock_confirmed)
    assert (confirmed_semantics["stock_definition_status"] == "confirmed_net_sellable").all()
    assert not confirmed_semantics["review_reasons"].str.contains(
        "stock_definition_pending_client_confirmation", regex=False
    ).any()


def test_config_rejects_invalid_layout_or_unparsed_stock_date():
    with pytest.raises(ValueError, match="data_start_row"):
        InventoryConfig(header_row=3, data_start_row=3)
    with pytest.raises(ValueError, match="stock_as_of"):
        InventoryConfig(stock_as_of="guess from filename")


def test_duplicate_historical_keys_rejected(inventory, historical):
    historical.loc[1, "product_key"] = historical.loc[0, "product_key"]
    with pytest.raises(ValueError, match="product_key"):
        build_inventory_crosswalk(inventory, historical)


def test_crosswalk_does_not_overwrite_existing_columns(inventory, historical):
    inventory["product_key"] = "existing-value"
    with pytest.raises(ValueError, match="reserved crosswalk columns"):
        build_inventory_crosswalk(inventory, historical)
