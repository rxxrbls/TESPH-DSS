"""Reusable stock-risk and MCA calculations.

The functions require current inventory, criterion values, thresholds, weights,
and directions as inputs. Historical Shopee orders are never treated as current
stock, product cost, supplier lead time, or stock-out history.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from analytics_calculations import _require_columns
from etl import find_column, product_key, standardize_product_value
from methodology_config import (
    MCA_CRITERIA as CONFIG_MCA_CRITERIA,
    MCA_DIRECTIONS,
    MCA_HIGH_PRIORITY_MIN,
    MCA_MEDIUM_PRIORITY_MIN,
    MCA_WEIGHTS,
    REPLENISHMENT_CONFIG,
    RISK_INDEX_MISSING_STOCK_VALUE,
    RISK_INDEX_ZERO_DEMAND_VALUE,
    STOCK_RISK_THRESHOLDS,
    StockRiskConfig,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_CURRENT_STOCK_PATH = (
    ROOT / "raw_data" / "current_stock" / "current_stock_inventory_2026-09-09.csv"
)
RAW_CURRENT_STOCK_EXPORT_PATH = (
    ROOT / "raw_data" / "current_stock" / "shopee_current_stock_raw_2026-09-09.xlsx"
)
CURRENT_STOCK_COLUMN = "Current Stock"
PENDING_THRESHOLDS_RISK = "Pending Thresholds"
STOCK_AS_OF_DATE_COLUMN = "Stock As-Of Date"
STOCK_AS_OF_DATE_ALIASES = (
    STOCK_AS_OF_DATE_COLUMN,
    "Stock As Of Date",
    "Inventory Date",
    "Inventory As-Of Date",
    "As Of Date",
    "As-Of Date",
)
STOCK_EXPORT_COLUMN_ALIASES = (
    CURRENT_STOCK_COLUMN,
    "Available Stock",
    "Stock",
    "Variation Stock",
    "et_title_variation_stock",
)
STOCK_IDENTIFIER_COLUMN_ALIASES = (
    "Category",
    "final_category",
    "product_key",
    "Product Key",
    "Product ID",
    "Item ID",
    "Variation ID",
    "Model ID",
    "Product Name",
    "Product",
    "Variation Name",
    "Variation",
    "Parent SKU",
    "SKU",
    "SKU #",
    "Variation SKU",
)
INVENTORY_MATCH_REVIEW_COLUMNS = (
    "crosswalk_product_key",
    "candidate_product_keys",
    "Candidate Product",
    "Candidate Category",
    "match_method",
    "match_status",
    "mapping_review_required",
    "inventory_review_required",
    "review_reasons",
    "stock_valid",
    "stock_issue",
    "missing_sku",
    "reused_sku",
    "duplicate_product_variation_id",
    "stock_as_of_status",
    "stock_definition_status",
)
MCA_CRITERIA = tuple(CONFIG_MCA_CRITERIA)


StockRiskThresholds = StockRiskConfig


def calculate_days_of_inventory(current_stock: float, average_daily_forecast_demand: float) -> float | None:
    """Calculate on-hand days at the forecast's mean daily demand rate."""

    values = np.asarray([current_stock, average_daily_forecast_demand], dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Stock and daily forecast demand must be finite and non-negative")
    if average_daily_forecast_demand == 0:
        return None
    return float(current_stock / average_daily_forecast_demand)


def _nonblank(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().ne("")


def _clean_text(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned.eq(""), pd.NA)


def _blank_value(value: object) -> bool:
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def _text_key(value: object, *, strip: bool = True) -> str | None:
    if _blank_value(value):
        return None
    text = str(value)
    return text.strip() if strip else text


def _inventory_name_pair(row: Mapping[str, object]) -> tuple[str, str] | None:
    product = row.get("standardized_product_name")
    variation = row.get("standardized_variation_name")
    if _blank_value(product):
        product = standardize_product_value(row.get("Product Name"))
    if _blank_value(variation):
        variation = standardize_product_value(row.get("Variation Name"))
    if _blank_value(product) or _blank_value(variation):
        return None
    return str(product), str(variation)


def _dimension_name_pair(row: Mapping[str, object]) -> tuple[str, str] | None:
    product = row.get("standardized Product Name", row.get("standardized_product_name"))
    variation = row.get(
        "standardized Variation Name", row.get("standardized_variation_name")
    )
    if _blank_value(product) or _blank_value(variation):
        return None
    return str(product), str(variation)


def _stock_issue(value: object) -> str:
    if _blank_value(value):
        return "missing_stock"
    if isinstance(value, bool):
        return "invalid_stock"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "invalid_stock"
    if not number.is_finite():
        return "invalid_stock"
    if number < 0:
        return "negative_stock"
    if number != number.to_integral_value():
        return "fractional_stock"
    return ""


def _excel_column_number(cell_reference: str) -> int:
    match = re.match(r"([A-Z]+)", cell_reference.upper())
    if not match:
        raise ValueError(f"Invalid Excel cell reference: {cell_reference}")
    column_number = 0
    for letter in match.group(1):
        column_number = column_number * 26 + ord(letter) - ord("A") + 1
    return column_number


def _read_xlsx_rows_from_xml(path: Path) -> pd.DataFrame:
    """Read raw worksheet cells when openpyxl rejects workbook view metadata."""

    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        worksheet_names = [
            name for name in archive.namelist() if name.startswith("xl/worksheets/")
        ]
        if not worksheet_names:
            raise ValueError(f"No worksheets found in {path}")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", namespace):
                shared_strings.append(
                    "".join(text.text or "" for text in item.findall(".//a:t", namespace))
                )

        worksheet = ET.fromstring(archive.read(sorted(worksheet_names)[0]))
        output_rows: list[list[object]] = []
        for row in worksheet.findall(".//a:sheetData/a:row", namespace):
            cells: dict[int, object] = {}
            for cell in row.findall("a:c", namespace):
                reference = cell.attrib.get("r", "A")
                column_number = _excel_column_number(reference)
                cell_type = cell.attrib.get("t")
                value_node = cell.find("a:v", namespace)
                if cell_type == "s" and value_node is not None:
                    value: object = shared_strings[int(value_node.text or 0)]
                elif cell_type == "inlineStr":
                    text_node = cell.find(".//a:t", namespace)
                    value = "" if text_node is None else text_node.text or ""
                else:
                    value = "" if value_node is None else value_node.text or ""
                cells[column_number] = value
            if cells:
                output_rows.append(
                    [cells.get(index, "") for index in range(1, max(cells) + 1)]
                )
        max_columns = max((len(row) for row in output_rows), default=0)
        return pd.DataFrame(
            [row + [""] * (max_columns - len(row)) for row in output_rows]
        )


def _read_stock_export_file(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Current-stock file not found: {source}")

    suffix = source.suffix.casefold()
    if suffix == ".csv":
        return pd.read_csv(source, header=None, dtype="object", low_memory=False)
    if suffix == ".xlsx":
        try:
            return pd.read_excel(source, header=None, dtype="object", engine="openpyxl")
        except ValueError:
            return _read_xlsx_rows_from_xml(source)
    raise ValueError(f"Unsupported current-stock file type: {suffix or '<none>'}")


def _promote_stock_export_header(stock_export: pd.DataFrame) -> pd.DataFrame:
    if find_column(
        stock_export.columns, *STOCK_IDENTIFIER_COLUMN_ALIASES
    ) and find_column(
        stock_export.columns, *STOCK_EXPORT_COLUMN_ALIASES
    ):
        return stock_export.copy()

    for row_index in range(min(len(stock_export), 25)):
        candidate_columns = []
        for position, value in enumerate(stock_export.iloc[row_index].tolist(), start=1):
            if pd.isna(value) or not str(value).strip():
                candidate_columns.append(f"Column {position}")
            else:
                candidate_columns.append(str(value).strip())
        if find_column(
            candidate_columns, *STOCK_IDENTIFIER_COLUMN_ALIASES
        ) and find_column(
            candidate_columns, *STOCK_EXPORT_COLUMN_ALIASES
        ):
            promoted = stock_export.iloc[row_index + 1 :].reset_index(drop=True).copy()
            promoted.columns = candidate_columns
            return promoted

    return stock_export.copy()


def prepare_current_stock_inventory(
    stock_export: pd.DataFrame,
    *,
    stock_as_of_date: str | pd.Timestamp | None = None,
    stock_column: str | None = None,
) -> pd.DataFrame:
    """Clean a Shopee/current-stock export without fabricating stock values.

    The returned DataFrame keeps the source product/SKU identifiers, calculates
    the same ``product_key`` used by the ETL when product and variation names
    are present, and standardizes the stock count as ``Current Stock``.
    """

    raw = _promote_stock_export_header(stock_export)
    resolved_stock_column = (
        stock_column
        if stock_column is not None
        else find_column(raw.columns, *STOCK_EXPORT_COLUMN_ALIASES)
    )
    if resolved_stock_column is None or resolved_stock_column not in raw.columns:
        raise ValueError("Current-stock input must include a stock column")

    product_id_column = find_column(raw.columns, "Product ID", "Item ID")
    variation_id_column = find_column(raw.columns, "Variation ID", "Model ID")
    product_name_column = find_column(raw.columns, "Product Name", "Product")
    variation_name_column = find_column(raw.columns, "Variation Name", "Variation")
    parent_sku_column = find_column(raw.columns, "Parent SKU")
    sku_column = find_column(raw.columns, "SKU", "SKU #", "Variation SKU")
    category_column = find_column(raw.columns, "Category", "final_category")
    product_key_column = find_column(raw.columns, "product_key", "Product Key")
    stock_as_of_date_column = find_column(raw.columns, *STOCK_AS_OF_DATE_ALIASES)
    identifier_columns = [
        column
        for column in (
            category_column,
            product_key_column,
            product_id_column,
            variation_id_column,
            product_name_column,
            variation_name_column,
            parent_sku_column,
            sku_column,
        )
        if column is not None
    ]
    if not identifier_columns:
        raise ValueError("Current-stock input must include a product or SKU identifier")

    source = raw.loc[raw[identifier_columns].apply(_nonblank).any(axis=1)].copy()
    if source.empty:
        return pd.DataFrame(
            columns=[
                "Product ID",
                "Variation ID",
                "Product Name",
                "Variation Name",
                "Parent SKU",
                "SKU",
                "Category",
                CURRENT_STOCK_COLUMN,
                STOCK_AS_OF_DATE_COLUMN,
                "standardized_product_name",
                "standardized_variation_name",
                "product_key",
            ]
        )

    stock = pd.to_numeric(source[resolved_stock_column], errors="coerce")
    stock_issues = source[resolved_stock_column].map(_stock_issue)
    if stock_issues.ne("").any():
        raise ValueError("Current stock must be a non-negative whole-number count")

    result = pd.DataFrame(index=source.index)
    optional_columns = {
        "Product ID": product_id_column,
        "Variation ID": variation_id_column,
        "Product Name": product_name_column,
        "Variation Name": variation_name_column,
        "Parent SKU": parent_sku_column,
        "SKU": sku_column,
        "Category": category_column,
    }
    for output_column, input_column in optional_columns.items():
        if input_column is None:
            result[output_column] = pd.NA
        else:
            result[output_column] = _clean_text(source[input_column])

    result[CURRENT_STOCK_COLUMN] = stock.astype(float)
    if stock_as_of_date is not None:
        as_of_date = pd.to_datetime(stock_as_of_date, errors="raise")
        result[STOCK_AS_OF_DATE_COLUMN] = as_of_date
    elif stock_as_of_date_column is not None:
        source_dates = source[stock_as_of_date_column]
        parsed_dates = pd.to_datetime(source_dates, errors="coerce")
        invalid_dates = _nonblank(source_dates) & parsed_dates.isna()
        if invalid_dates.any():
            raise ValueError("Stock as-of date must be parseable when provided")
        result[STOCK_AS_OF_DATE_COLUMN] = parsed_dates
    else:
        result[STOCK_AS_OF_DATE_COLUMN] = pd.NaT

    result["standardized_product_name"] = result["Product Name"].map(
        standardize_product_value
    )
    result["standardized_variation_name"] = result["Variation Name"].map(
        standardize_product_value
    )
    has_product_name = _nonblank(result["standardized_product_name"])
    if product_key_column is None:
        result["product_key"] = pd.NA
    else:
        result["product_key"] = _clean_text(source[product_key_column])
    missing_product_key = ~_nonblank(result["product_key"])
    needs_generated_key = has_product_name & missing_product_key
    result.loc[needs_generated_key, "product_key"] = [
        product_key(product, variation)
        for product, variation in zip(
            result.loc[needs_generated_key, "standardized_product_name"],
            result.loc[needs_generated_key, "standardized_variation_name"],
        )
    ]
    return result.reset_index(drop=True)


def load_current_stock_inventory(
    path: str | Path | None = None,
    *,
    stock_as_of_date: str | pd.Timestamp | None = None,
    stock_column: str | None = None,
) -> pd.DataFrame:
    """Load and clean a CSV/XLSX current-stock export for KAN-54."""

    return prepare_current_stock_inventory(
        _read_stock_export_file(DEFAULT_CURRENT_STOCK_PATH if path is None else path),
        stock_as_of_date=stock_as_of_date,
        stock_column=stock_column,
    )


def validate_current_stock_inventory(
    inventory: pd.DataFrame,
    *,
    current_stock_column: str = CURRENT_STOCK_COLUMN,
) -> dict[str, object]:
    """Validate cleaned current stock without approving mapping or thresholds."""

    _require_columns(inventory, [current_stock_column])
    identifier_columns = [
        column for column in STOCK_IDENTIFIER_COLUMN_ALIASES if column in inventory.columns
    ]
    if not identifier_columns:
        raise ValueError("Current-stock inventory must include an item identifier")

    product_id_column = find_column(inventory.columns, "Product ID", "Item ID")
    variation_id_column = find_column(inventory.columns, "Variation ID", "Model ID")
    sku_column = find_column(inventory.columns, "SKU", "SKU #", "Variation SKU")
    stock_as_of_column = find_column(inventory.columns, *STOCK_AS_OF_DATE_ALIASES)

    stock_issues = inventory[current_stock_column].map(_stock_issue)
    has_identifier = inventory[identifier_columns].apply(_nonblank).any(axis=1)
    sku_values = (
        inventory[sku_column].map(_text_key)
        if sku_column is not None
        else pd.Series([None] * len(inventory), index=inventory.index)
    )
    sku_counts = Counter(value for value in sku_values if value is not None)

    listing_pairs: list[tuple[str, str] | None] = []
    for row in inventory.to_dict("records"):
        product_id = _text_key(row.get(product_id_column)) if product_id_column else None
        variation_id = (
            _text_key(row.get(variation_id_column)) if variation_id_column else None
        )
        listing_pairs.append(
            (product_id, variation_id)
            if product_id is not None and variation_id is not None
            else None
        )
    listing_pair_counts = Counter(pair for pair in listing_pairs if pair is not None)

    if stock_as_of_column is None:
        stock_as_of_status = pd.Series(
            ["pending_confirmation"] * len(inventory), index=inventory.index
        )
    else:
        stock_as_of_status = np.where(
            _nonblank(inventory[stock_as_of_column]),
            "provided",
            "pending_confirmation",
        )
        stock_as_of_status = pd.Series(stock_as_of_status, index=inventory.index)

    checks = []
    for position, (index, row) in enumerate(inventory.iterrows()):
        errors: list[str] = []
        warnings: list[str] = []
        stock_issue = stock_issues.loc[index]
        sku = sku_values.loc[index]
        listing_pair = listing_pairs[position]
        duplicate_listing = (
            listing_pair is not None and listing_pair_counts[listing_pair] > 1
        )

        if stock_issue:
            errors.append(str(stock_issue))
        if not bool(has_identifier.loc[index]):
            errors.append("missing_inventory_identifier")
        if duplicate_listing:
            errors.append("duplicate_product_variation_id")
        if sku is None:
            warnings.append("missing_sku")
        elif sku_counts[sku] > 1:
            warnings.append("reused_sku_stock_pool_unconfirmed")
        if _inventory_name_pair(row.to_dict()) is None:
            warnings.append("missing_product_or_variation_name")
        if stock_as_of_status.loc[index] != "provided":
            warnings.append("stock_as_of_pending_confirmation")

        checks.append(
            {
                "row_position": position,
                "valid": not errors,
                "stock_valid": not stock_issue,
                "stock_issue": stock_issue,
                "missing_identifier": not bool(has_identifier.loc[index]),
                "missing_sku": sku is None,
                "reused_sku": bool(sku is not None and sku_counts[sku] > 1),
                "duplicate_product_variation_id": duplicate_listing,
                "stock_as_of_status": stock_as_of_status.loc[index],
                "errors": " | ".join(errors),
                "warnings": " | ".join(warnings),
            }
        )

    row_checks = pd.DataFrame(
        checks,
        columns=[
            "row_position",
            "valid",
            "stock_valid",
            "stock_issue",
            "missing_identifier",
            "missing_sku",
            "reused_sku",
            "duplicate_product_variation_id",
            "stock_as_of_status",
            "errors",
            "warnings",
        ],
    )
    return {
        "valid": bool(checks) and bool(row_checks["valid"].all()),
        "row_count": len(inventory),
        "row_checks": row_checks,
        "stock_as_of_status": (
            "provided"
            if bool(stock_as_of_status.eq("provided").all())
            else "pending_confirmation"
        ),
        "stock_definition_status": "pending_client_confirmation",
    }


def build_inventory_product_crosswalk(
    inventory: pd.DataFrame,
    product_dimension: pd.DataFrame,
    *,
    current_stock_column: str = CURRENT_STOCK_COLUMN,
    product_key_column: str = "product_key",
) -> pd.DataFrame:
    """Build candidate product/category matches while keeping review flags visible."""

    report = validate_current_stock_inventory(
        inventory, current_stock_column=current_stock_column
    )
    product_dimension_key = find_column(
        product_dimension.columns, product_key_column, "product_key", "Product Key"
    )
    if product_dimension_key is None:
        raise ValueError("Product dimension must include product_key")
    if product_dimension[product_dimension_key].map(_blank_value).any():
        raise ValueError("Product dimension product_key must be nonblank")
    if product_dimension[product_dimension_key].duplicated().any():
        raise ValueError("Product dimension must contain one row per product_key")

    added_columns = set(INVENTORY_MATCH_REVIEW_COLUMNS)
    if added_columns.intersection(inventory.columns):
        raise ValueError("Inventory already contains reserved crosswalk columns")

    dimension_records = product_dimension.to_dict("records")
    dimension_keys = {str(row[product_dimension_key]) for row in dimension_records}
    sku_column = find_column(product_dimension.columns, "SKU", "SKU Reference No.")
    product_column = find_column(product_dimension.columns, "final_base_product_name")
    category_column = find_column(product_dimension.columns, "final_category", "Category")

    metadata_by_key: dict[str, dict[str, object]] = {}
    sku_index: dict[str, set[str]] = defaultdict(set)
    sku_alias_index: dict[str, set[str]] = defaultdict(set)
    name_index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in dimension_records:
        key = str(row[product_dimension_key])
        metadata_by_key[key] = row
        sku = _text_key(row.get(sku_column)) if sku_column is not None else None
        if sku is not None:
            if " | " in sku:
                for token in sku.split(" | "):
                    token = token.strip()
                    if token:
                        sku_alias_index[token].add(key)
            else:
                sku_index[sku].add(key)
        pair = _dimension_name_pair(row)
        if pair is not None:
            name_index[pair].add(key)

    inventory_sku_column = find_column(inventory.columns, "SKU", "SKU #", "Variation SKU")
    inventory_product_key_column = find_column(
        inventory.columns, product_key_column, "product_key", "Product Key"
    )
    rows = inventory.to_dict("records")
    name_pairs = [_inventory_name_pair(row) for row in rows]
    name_pair_counts = Counter(pair for pair in name_pairs if pair is not None)

    crosswalk_records = []
    row_checks = report["row_checks"].to_dict("records")  # type: ignore[index]
    for row, pair, check in zip(rows, name_pairs, row_checks):
        reasons: list[str] = []
        direct_key = (
            _text_key(row.get(inventory_product_key_column))
            if inventory_product_key_column is not None
            else None
        )
        sku = (
            _text_key(row.get(inventory_sku_column))
            if inventory_sku_column is not None
            else None
        )
        direct_candidates = (
            {direct_key} if direct_key is not None and direct_key in dimension_keys else set()
        )
        sku_candidates = set()
        sku_alias_candidates = set()
        if sku is not None:
            sku_candidates = sku_index.get(sku, set())
            sku_alias_candidates = sku_alias_index.get(sku, set())
        name_candidates = name_index.get(pair, set()) if pair is not None else set()

        if direct_key is not None and direct_key not in dimension_keys:
            reasons.append("product_key_not_in_dimension")

        if direct_candidates:
            method = "product_key"
            candidates = set(direct_candidates)
            if sku_candidates and sku_candidates != direct_candidates:
                candidates |= sku_candidates
                reasons.append("product_key_sku_conflict")
            if sku_alias_candidates:
                candidates |= sku_alias_candidates
                reasons.append("historical_multi_value_sku")
            if name_candidates and name_candidates != direct_candidates:
                candidates |= name_candidates
                reasons.append("product_key_name_conflict")
        elif sku_candidates or sku_alias_candidates:
            method = "exact_sku" if sku_candidates else "historical_sku_alias_review"
            candidates = set(sku_candidates) | set(sku_alias_candidates)
            if sku_alias_candidates:
                reasons.append("historical_multi_value_sku")
            if name_candidates and name_candidates != candidates:
                candidates |= name_candidates
                reasons.append("sku_name_conflict")
        else:
            method = "normalized_name_variation" if name_candidates else "none"
            candidates = set(name_candidates)

        if check["reused_sku"]:
            reasons.append("reused_sku_stock_pool_unconfirmed")
        if check["duplicate_product_variation_id"]:
            reasons.append("duplicate_product_variation_id")
        if pair is not None and name_pair_counts[pair] > 1:
            reasons.append("repeated_current_name_pair")
        if len(candidates) > 1:
            reasons.append("multiple_historical_candidates")
        if not candidates:
            reasons.append("unmatched")
        if check["errors"]:
            reasons.append(str(check["errors"]))
        if pair is None:
            reasons.append("missing_product_or_variation_name")

        mapping_review_required = len(candidates) != 1 or bool(reasons)
        match_status = (
            "unmatched"
            if not candidates
            else "review_required"
            if mapping_review_required
            else "candidate"
        )
        if check["stock_as_of_status"] != "provided":
            reasons.append("stock_as_of_pending_confirmation")
        reasons.append("stock_definition_pending_client_confirmation")

        single_key = next(iter(candidates)) if len(candidates) == 1 else pd.NA
        metadata = metadata_by_key.get(single_key, {}) if not pd.isna(single_key) else {}
        crosswalk_records.append(
            {
                "crosswalk_product_key": single_key,
                "candidate_product_keys": " | ".join(sorted(candidates)),
                "Candidate Product": metadata.get(product_column, pd.NA)
                if product_column is not None
                else pd.NA,
                "Candidate Category": metadata.get(category_column, pd.NA)
                if category_column is not None
                else pd.NA,
                "match_method": method,
                "match_status": match_status,
                "mapping_review_required": mapping_review_required,
                "inventory_review_required": (
                    mapping_review_required
                    or not check["stock_valid"]
                    or check["stock_as_of_status"] != "provided"
                    or report["stock_definition_status"] != "confirmed"
                ),
                "review_reasons": " | ".join(dict.fromkeys(reasons)),
                "stock_valid": check["stock_valid"],
                "stock_issue": check["stock_issue"],
                "missing_sku": check["missing_sku"],
                "reused_sku": check["reused_sku"],
                "duplicate_product_variation_id": check[
                    "duplicate_product_variation_id"
                ],
                "stock_as_of_status": check["stock_as_of_status"],
                "stock_definition_status": report["stock_definition_status"],
            }
        )

    return pd.concat(
        [inventory.reset_index(drop=True), pd.DataFrame(crosswalk_records)],
        axis=1,
    )


def attach_inventory_product_metadata(
    inventory: pd.DataFrame,
    product_dimension: pd.DataFrame,
    *,
    product_key_column: str = "product_key",
) -> pd.DataFrame:
    """Attach governed product/category labels from the ETL product dimension."""

    _require_columns(inventory, [product_key_column])
    _require_columns(product_dimension, [product_key_column])
    metadata_columns = [product_key_column]
    rename_map = {}
    if "final_base_product_name" in product_dimension.columns:
        metadata_columns.append("final_base_product_name")
        rename_map["final_base_product_name"] = "Product"
    if "final_category" in product_dimension.columns:
        metadata_columns.append("final_category")
        rename_map["final_category"] = "Category"
    if len(metadata_columns) == 1:
        return inventory.copy()

    metadata = product_dimension[metadata_columns].copy()
    if metadata[product_key_column].dropna().duplicated().any():
        raise ValueError("Product dimension must contain one row per product_key")
    metadata = metadata.drop_duplicates(product_key_column)
    return inventory.merge(
        metadata.rename(columns=rename_map),
        on=product_key_column,
        how="left",
        validate="many_to_one",
    )


def aggregate_current_stock(
    inventory: pd.DataFrame,
    *,
    item_columns: Iterable[str],
    current_stock_column: str = CURRENT_STOCK_COLUMN,
) -> pd.DataFrame:
    """Aggregate inventory to the same grain used by the forecast output."""

    item_columns = list(item_columns)
    if not item_columns:
        raise ValueError("At least one inventory aggregation column is required")
    _require_columns(inventory, [*item_columns, current_stock_column])

    data = inventory.copy()
    valid_item_key = data[item_columns].apply(_nonblank).all(axis=1)
    data = data.loc[valid_item_key].copy()
    data[current_stock_column] = pd.to_numeric(data[current_stock_column], errors="coerce")
    if data[current_stock_column].isna().any():
        raise ValueError("Current stock must be numeric before aggregation")
    if data[current_stock_column].lt(0).any():
        raise ValueError("Current stock cannot be negative")

    if data.empty:
        columns = [*item_columns, CURRENT_STOCK_COLUMN]
        if STOCK_AS_OF_DATE_COLUMN in inventory.columns:
            columns.append(STOCK_AS_OF_DATE_COLUMN)
        return pd.DataFrame(columns=columns)

    aggregations: dict[str, tuple[str, str]] = {
        CURRENT_STOCK_COLUMN: (current_stock_column, "sum")
    }
    if STOCK_AS_OF_DATE_COLUMN in data.columns:
        data[STOCK_AS_OF_DATE_COLUMN] = pd.to_datetime(
            data[STOCK_AS_OF_DATE_COLUMN], errors="coerce"
        )
        aggregations[STOCK_AS_OF_DATE_COLUMN] = (STOCK_AS_OF_DATE_COLUMN, "max")
    return (
        data.groupby(item_columns, dropna=False, sort=True, observed=False)
        .agg(**aggregations)
        .reset_index()
    )


def calculate_stock_out_risk(
    forecasts: pd.DataFrame,
    inventory: pd.DataFrame,
    *,
    item_columns: Iterable[str],
    forecast_horizon_days: int,
    forecast_column: str = "Forecast",
    current_stock_column: str = CURRENT_STOCK_COLUMN,
    thresholds: StockRiskThresholds | None = None,
) -> pd.DataFrame:
    """KAN-54: compare current stock with forecast demand using DOI and a risk index.

    Risk Index is the uncovered share of horizon demand:
    ``max(Forecast Demand - Current Stock, 0) / Forecast Demand``.
    The DOI risk labels use caller-supplied operational thresholds.
    """

    item_columns = list(item_columns)
    if not item_columns:
        raise ValueError("At least one item column is required")
    _require_columns(forecasts, [*item_columns, forecast_column])
    _require_columns(inventory, [*item_columns, current_stock_column])
    if not isinstance(forecast_horizon_days, int) or isinstance(forecast_horizon_days, bool):
        raise ValueError("forecast_horizon_days must be a positive integer")
    if forecast_horizon_days < 1:
        raise ValueError("forecast_horizon_days must be a positive integer")
    thresholds = thresholds or STOCK_RISK_THRESHOLDS
    thresholds.validate()
    if forecasts.duplicated(item_columns).any():
        raise ValueError("Forecasts must contain one row per requested item key")
    if inventory.duplicated(item_columns).any():
        raise ValueError("Inventory must contain one row per requested item key")

    result = forecasts.copy()
    result[forecast_column] = pd.to_numeric(result[forecast_column], errors="coerce")
    if (
        result[forecast_column].isna().any()
        or not np.isfinite(result[forecast_column].to_numpy(dtype=float)).all()
        or result[forecast_column].lt(0).any()
    ):
        raise ValueError("Forecast must contain finite non-negative values")
    stock = inventory[[*item_columns, current_stock_column]].copy()
    stock[current_stock_column] = pd.to_numeric(stock[current_stock_column], errors="coerce")
    finite_stock = np.isfinite(stock[current_stock_column].fillna(0).to_numpy(dtype=float))
    invalid_stock = stock[current_stock_column].notna() & (
        stock[current_stock_column].lt(0) | ~finite_stock
    )
    if invalid_stock.any():
        raise ValueError("Current stock cannot be negative")
    result = result.merge(stock, on=item_columns, how="left", validate="one_to_one")
    result = result.rename(
        columns={
            forecast_column: "Forecast Demand",
            current_stock_column: CURRENT_STOCK_COLUMN,
        }
    )

    positive_demand = result["Forecast Demand"].gt(0)
    has_stock = result[CURRENT_STOCK_COLUMN].notna()
    result["Forecast Daily Demand"] = result["Forecast Demand"] / forecast_horizon_days
    result["Days of Inventory"] = np.nan
    result.loc[positive_demand & has_stock, "Days of Inventory"] = [
        calculate_days_of_inventory(stock_value, daily_demand)
        for stock_value, daily_demand in zip(
            result.loc[positive_demand & has_stock, CURRENT_STOCK_COLUMN],
            result.loc[positive_demand & has_stock, "Forecast Daily Demand"],
        )
    ]
    result["Stock Gap"] = np.nan
    result.loc[has_stock, "Stock Gap"] = (
        result.loc[has_stock, "Forecast Demand"]
        - result.loc[has_stock, CURRENT_STOCK_COLUMN]
    ).clip(lower=0.0)
    result["Risk Index"] = RISK_INDEX_MISSING_STOCK_VALUE
    result.loc[positive_demand & has_stock, "Risk Index"] = (
        result.loc[positive_demand & has_stock, "Stock Gap"]
        / result.loc[positive_demand & has_stock, "Forecast Demand"]
    ).clip(lower=0.0, upper=1.0)
    result.loc[~positive_demand & has_stock, "Risk Index"] = (
        RISK_INDEX_ZERO_DEMAND_VALUE
    )

    doi = result["Days of Inventory"]
    result["Stock-Out Risk"] = np.select(
        [
            ~positive_demand,
            ~has_stock,
            doi.le(thresholds.critical_max_days),
            doi.le(thresholds.high_max_days),
            doi.le(thresholds.medium_max_days),
        ],
        [
            "No Forecast Demand",
            "Insufficient Stock Data",
            "Critical",
            "High",
            "Medium",
        ],
        default="Low",
    )
    calculated_columns = [
        CURRENT_STOCK_COLUMN,
        "Forecast Demand",
        "Forecast Daily Demand",
        "Days of Inventory",
        "Stock Gap",
        "Risk Index",
        "Stock-Out Risk",
    ]
    passthrough = [
        column for column in forecasts.columns if column not in {*item_columns, forecast_column}
    ]
    return result[[*item_columns, *passthrough, *calculated_columns]]


def calculate_mca_scores(
    alternatives: pd.DataFrame,
    *,
    identifier_columns: Iterable[str],
    weights: Mapping[str, float] | None = None,
    directions: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Return normalized criterion contributions and deterministic SKU ranking."""

    identifier_columns = list(identifier_columns)
    if not identifier_columns:
        raise ValueError("At least one MCA identifier column is required")
    weights = MCA_WEIGHTS if weights is None else weights
    directions = MCA_DIRECTIONS if directions is None else directions
    _require_columns(alternatives, [*identifier_columns, *MCA_CRITERIA])
    if alternatives[identifier_columns].isna().any().any():
        raise ValueError("MCA identifiers must not be missing")
    if alternatives.duplicated(identifier_columns).any():
        raise ValueError("MCA identifiers must be unique")
    missing_weights = [criterion for criterion in MCA_CRITERIA if criterion not in weights]
    missing_directions = [criterion for criterion in MCA_CRITERIA if criterion not in directions]
    if missing_weights:
        raise ValueError("Missing MCA weights: " + ", ".join(missing_weights))
    if missing_directions:
        raise ValueError("Missing MCA directions: " + ", ".join(missing_directions))

    weight_values = np.asarray([weights[criterion] for criterion in MCA_CRITERIA], dtype=float)
    if not np.isfinite(weight_values).all() or (weight_values < 0).any():
        raise ValueError("MCA weights must be finite and non-negative")
    if not np.isclose(weight_values.sum(), 1.0):
        raise ValueError("MCA weights must sum to 1.00")
    invalid_directions = {
        criterion: directions[criterion]
        for criterion in MCA_CRITERIA
        if directions[criterion] not in {"benefit", "cost"}
    }
    if invalid_directions:
        raise ValueError("Each MCA direction must be benefit or cost")

    result = alternatives.copy()
    normalized_columns = []
    for criterion in MCA_CRITERIA:
        values = pd.to_numeric(result[criterion], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"MCA criterion must be complete and numeric: {criterion}")
        minimum = float(values.min())
        maximum = float(values.max())
        normalized_name = f"Normalized {criterion}"
        normalized_columns.append(normalized_name)
        if np.isclose(maximum, minimum):
            result[normalized_name] = 0.5
        elif directions[criterion] == "benefit":
            result[normalized_name] = (values - minimum) / (maximum - minimum)
        else:
            result[normalized_name] = (maximum - values) / (maximum - minimum)

    contribution_columns = []
    result["SKU Priority Score"] = 0.0
    for criterion, normalized_name in zip(MCA_CRITERIA, normalized_columns):
        contribution_name = f"Weighted {criterion}"
        contribution_columns.append(contribution_name)
        result[contribution_name] = float(weights[criterion]) * result[normalized_name]
        result["SKU Priority Score"] += result[contribution_name]
    result["Priority Level"] = np.select(
        [
            result["SKU Priority Score"].ge(MCA_HIGH_PRIORITY_MIN),
            result["SKU Priority Score"].ge(MCA_MEDIUM_PRIORITY_MIN),
        ],
        ["High", "Medium"],
        default="Low",
    )
    result = rank_priority_scores(
        result, identifier_columns=identifier_columns, score_column="SKU Priority Score"
    )
    ordered = [
        *identifier_columns,
        *MCA_CRITERIA,
        *normalized_columns,
        *contribution_columns,
        "SKU Priority Score",
        "Priority Rank",
        "Priority Level",
    ]
    return result[ordered]


def rank_priority_scores(
    alternatives: pd.DataFrame,
    *,
    identifier_columns: Iterable[str],
    score_column: str = "SKU Priority Score",
) -> pd.DataFrame:
    """Rank descending scores, then identifiers ascending for exact ties."""

    identifier_columns = list(identifier_columns)
    _require_columns(alternatives, [*identifier_columns, score_column])
    scores = pd.to_numeric(alternatives[score_column], errors="coerce")
    if scores.isna().any() or not np.isfinite(scores.to_numpy(dtype=float)).all():
        raise ValueError("Priority scores must be finite numeric values")
    result = alternatives.copy()
    result[score_column] = scores
    result = result.sort_values(
        [score_column, *identifier_columns],
        ascending=[False, *([True] * len(identifier_columns))],
        kind="stable",
    ).reset_index(drop=True)
    result["Priority Rank"] = np.arange(1, len(result) + 1, dtype=int)
    return result


def classify_mca_priority(score: float) -> str:
    """Classify the 0..1 weighted score into fixed, explainable thirds."""

    if not np.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("MCA score must be finite and between 0 and 1")
    if score >= MCA_HIGH_PRIORITY_MIN:
        return "High"
    if score >= MCA_MEDIUM_PRIORITY_MIN:
        return "Medium"
    return "Low"


def calculate_weighted_contributions(
    normalized_scores: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Calculate each normalized criterion's configured weighted contribution."""

    weights = MCA_WEIGHTS if weights is None else weights
    missing = [criterion for criterion in MCA_CRITERIA if criterion not in normalized_scores or criterion not in weights]
    if missing:
        raise ValueError("Missing MCA values or weights: " + ", ".join(missing))
    return {
        criterion: float(normalized_scores[criterion]) * float(weights[criterion])
        for criterion in MCA_CRITERIA
    }


def calculate_priority_score(weighted_contributions: Mapping[str, float]) -> float:
    """Sum the six weighted contributions into one priority score."""

    missing = [criterion for criterion in MCA_CRITERIA if criterion not in weighted_contributions]
    if missing:
        raise ValueError("Missing weighted contributions: " + ", ".join(missing))
    return float(sum(float(weighted_contributions[criterion]) for criterion in MCA_CRITERIA))


def calculate_sku_priority(
    sku_values: Mapping[str, float],
    dataset_minimums: Mapping[str, float],
    dataset_maximums: Mapping[str, float],
) -> dict[str, object]:
    """Compatibility entry point that delegates every calculation to this module."""

    normalized = {}
    for criterion in MCA_CRITERIA:
        if criterion not in sku_values or criterion not in dataset_minimums or criterion not in dataset_maximums:
            raise ValueError(f"Missing MCA value or bound for: {criterion}")
        normalized[criterion] = min_max_normalize(
            sku_values[criterion], dataset_minimums[criterion],
            dataset_maximums[criterion], MCA_DIRECTIONS[criterion],
        )
    contributions = calculate_weighted_contributions(normalized)
    score = calculate_priority_score(contributions)
    return {
        "normalized_scores": normalized,
        "weighted_contributions": contributions,
        "priority_score": score,
        "priority_level": classify_mca_priority(score),
    }


def classify_recommendation_priority(
    recommended_quantity: float,
    stock_risk: str,
    mca_priority: str | None,
) -> str:
    """Use the more urgent of stock risk and MCA; Critical always means Immediate."""

    if not np.isfinite(recommended_quantity) or recommended_quantity < 0:
        raise ValueError("Recommended quantity must be finite and non-negative")
    if recommended_quantity == 0:
        return "None"
    if stock_risk == "Critical":
        return "Immediate"
    levels = {"High": 3, "Medium": 2, "Low": 1}
    if stock_risk not in levels:
        raise ValueError(f"Unsupported stock-risk level for recommendation: {stock_risk}")
    if mca_priority is not None and mca_priority not in levels:
        raise ValueError(f"Unsupported MCA priority: {mca_priority}")
    level = max(levels[stock_risk], levels.get(mca_priority, 1))
    return {3: "High", 2: "Medium", 1: "Low"}[level]


def recommendation_action(recommended_quantity: float, stock_risk: str) -> str:
    """Return the deterministic action label for a quantity and demand state."""

    if stock_risk == "No Forecast Demand":
        return "Monitor; no forecast demand"
    return "Replenish to target" if recommended_quantity > 0 else "Maintain stock"


def min_max_normalize(
    value: float,
    minimum: float,
    maximum: float,
    direction: str,
) -> float:
    """Normalize one value; a constant criterion receives a neutral 0.5."""

    values = np.asarray([value, minimum, maximum], dtype=float)
    if not np.isfinite(values).all() or maximum < minimum:
        raise ValueError("MCA values and bounds must be finite and ordered")
    if direction not in {"benefit", "cost"}:
        raise ValueError("MCA direction must be benefit or cost")
    if maximum == minimum:
        return 0.5
    if direction == "benefit":
        return float((value - minimum) / (maximum - minimum))
    return float((maximum - value) / (maximum - minimum))


def calculate_safety_stock(
    forecast_demand: float,
    *,
    forecast_horizon_days: int,
    safety_stock_days: int = REPLENISHMENT_CONFIG.safety_stock_days,
) -> int:
    """Use a configured number of mean-forecast demand days as a simple buffer."""

    if not np.isfinite(forecast_demand) or forecast_demand < 0:
        raise ValueError("Forecast demand must be finite and non-negative")
    if forecast_horizon_days < 1 or safety_stock_days < 0:
        raise ValueError("Forecast horizon must be positive and safety days non-negative")
    average_daily_demand = forecast_demand / forecast_horizon_days
    return int(np.ceil(average_daily_demand * safety_stock_days))


def calculate_target_stock_level(
    forecast_demand: float,
    *,
    forecast_horizon_days: int,
    lead_time_days: int = REPLENISHMENT_CONFIG.supplier_lead_time_days,
    review_period_days: int = REPLENISHMENT_CONFIG.review_period_days,
    safety_stock_days: int = REPLENISHMENT_CONFIG.safety_stock_days,
) -> int:
    """Target mean demand over lead+review days, plus configured safety stock.

    If the requested protection period exceeds the forecast horizon, the
    forecast's mean daily rate is extended deterministically across that period.
    """

    if not np.isfinite(forecast_demand) or forecast_demand < 0:
        raise ValueError("Forecast demand must be finite and non-negative")
    if forecast_horizon_days < 1:
        raise ValueError("Forecast horizon must be positive")
    REPLENISHMENT_CONFIG.validate()
    if any(
        isinstance(days, bool) or not isinstance(days, int) or days < 0
        for days in (lead_time_days, review_period_days, safety_stock_days)
    ):
        raise ValueError("Lead, review, and safety days must be non-negative integers")
    if lead_time_days < 1:
        raise ValueError("Lead time must be positive")
    average_daily_demand = forecast_demand / forecast_horizon_days
    protection_demand = int(np.ceil(average_daily_demand * (lead_time_days + review_period_days)))
    safety_stock = calculate_safety_stock(
        forecast_demand,
        forecast_horizon_days=forecast_horizon_days,
        safety_stock_days=safety_stock_days,
    )
    return protection_demand + safety_stock


def calculate_replenishment_quantity(target_stock_level: float, current_stock: float) -> int:
    """Return whole units needed to reach target stock, never a negative amount."""

    values = np.asarray([target_stock_level, current_stock], dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Target stock and current stock must be finite and non-negative")
    return max(0, int(np.ceil(target_stock_level - current_stock)))
