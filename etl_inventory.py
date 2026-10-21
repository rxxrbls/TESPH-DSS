"""Read-only client inventory validation and historical mapping candidates.

All results stay in memory. This module never writes a crosswalk or frozen output,
aggregates stock, approves a stock pool, or calculates predictive/prescriptive metrics.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook

from etl import standardize_product_value, validate_final_schema
from etl_config import INVENTORY_COLUMNS, InventoryConfig


def _blank(value) -> bool:
    return bool(pd.isna(value)) or (isinstance(value, str) and not value.strip())


def _sku(value):
    # Exact, case-sensitive text; no trimming, numeric conversion, or pipe splitting.
    return None if _blank(value) else str(value)


def _identifier(value):
    if _blank(value) or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number != number.to_integral_value():
            return None
        return str(int(number))
    except (InvalidOperation, ValueError):
        return None


def _name_pair(product, variation):
    product = standardize_product_value(product)
    variation = standardize_product_value(variation)
    if _blank(product) or _blank(variation):
        return None
    return product, variation


def _check_columns(columns, expected) -> None:
    columns = list(columns)
    missing = [name for name in expected if name not in columns]
    duplicates = [name for name, count in Counter(columns).items() if count > 1]
    if missing or duplicates:
        raise ValueError(f"Invalid inventory schema: missing={missing}; duplicate={duplicates}")


def _without_view_metadata(stream) -> BytesIO:
    """Ignore Excel display settings in memory, never alter the source archive.

    This Shopee export uses activePane='bottom_left', which openpyxl rejects.
    Worksheet views have no bearing on cell values, types, formulas, or headers.
    """
    result = BytesIO()
    with ZipFile(stream) as source, ZipFile(result, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(".xml"):
                root = ElementTree.fromstring(content)
                views = root.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetViews")
                if views is not None:
                    root.remove(views)
                    content = ElementTree.tostring(root, encoding="utf-8")
            target.writestr(entry, content)
    result.seek(0)
    return result


def load_current_inventory(config: InventoryConfig | None = None) -> pd.DataFrame:
    """Read the configured header and data rows, preserving literal source cells.

    Blank cells remain missing (None); text such as SKU 'NA' stays text. Formula
    cells remain formulas and will not be treated as verified numeric stock.
    Worksheet row numbers are retained in DataFrame attrs for validation reports.
    """
    config = config or InventoryConfig()
    with config.source_path.open("rb") as source, _without_view_metadata(source) as stream:
        workbook = load_workbook(stream, read_only=True, data_only=False)
        try:
            if config.sheet_name not in workbook.sheetnames:
                raise ValueError(f"Inventory sheet not found: {config.sheet_name}")
            sheet = workbook[config.sheet_name]
            # This client export declares dimension A1 despite having 1,986 rows.
            sheet.reset_dimensions()
            rows = sheet.iter_rows(min_row=config.header_row, values_only=True)
            header = list(next(rows, ()))
            _check_columns(header, tuple(dict.fromkeys(INVENTORY_COLUMNS + config.expected_columns)))
            values, source_rows = [], []
            for number, cells in enumerate(rows, start=config.header_row + 1):
                if number < config.data_start_row or all(_blank(v) for v in cells):
                    continue
                if len(cells) > len(header) and any(not _blank(v) for v in cells[len(header):]):
                    raise ValueError(f"Inventory row {number} has data beyond the header")
                values.append(list(cells[:len(header)]) + [None] * max(0, len(header) - len(cells)))
                source_rows.append(number)
        finally:
            workbook.close()
    if not values:
        raise ValueError("Inventory contains no data rows")
    frame = pd.DataFrame(values, columns=header, dtype=object)
    frame.attrs["source_rows"] = tuple(source_rows)
    frame.attrs["source_path"] = str(config.source_path)
    frame.attrs["sheet_name"] = config.sheet_name
    return frame


def _stock_issue(value) -> str:
    if _blank(value):
        return "missing_stock"
    if isinstance(value, bool):
        return "invalid_stock"
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return "invalid_stock"
    if not number.is_finite():
        return "invalid_stock"
    if number < 0:
        return "negative_stock"
    if number != number.to_integral_value():
        return "fractional_stock"
    return ""


def validate_current_inventory(frame: pd.DataFrame, config: InventoryConfig | None = None) -> dict:
    """Report errors and review flags without filling or altering any source cell.

    Missing/reused SKUs are review flags, not validation errors. 'valid' describes
    identifiers and stock syntax only; it does not confirm physical stock or date.
    """
    config = config or InventoryConfig()
    _check_columns(frame.columns, tuple(dict.fromkeys(INVENTORY_COLUMNS + config.expected_columns)))
    records = frame.to_dict("records")
    identifiers = [(_identifier(r["Product ID"]), _identifier(r["Variation ID"])) for r in records]
    id_counts = Counter(pair for pair in identifiers if None not in pair)
    sku_counts = Counter(_sku(r["SKU"]) for r in records if _sku(r["SKU"]) is not None)
    source_rows = frame.attrs.get("source_rows", ())
    checks = []
    for position, (record, pair) in enumerate(zip(records, identifiers)):
        errors, warnings = [], []
        for field, identifier in zip(("Product ID", "Variation ID"), pair):
            if identifier is None:
                errors.append(f"invalid_or_missing_{field}")
        duplicate = None not in pair and id_counts[pair] > 1
        if duplicate:
            errors.append("duplicate_product_variation_id")
        stock_issue = _stock_issue(record["Stock"])
        if stock_issue:
            errors.append(stock_issue)
        sku = _sku(record["SKU"])
        if sku is None:
            warnings.append("missing_sku")
        reused = sku is not None and sku_counts[sku] > 1
        if reused:
            warnings.append("reused_sku_stock_pool_unconfirmed")
        if _name_pair(record["Product Name"], record["Variation Name"]) is None:
            warnings.append("missing_product_or_variation_name")
        checks.append({
            "row_position": position,
            "source_row": source_rows[position] if len(source_rows) == len(records) else pd.NA,
            "valid": not errors, "stock_valid": not stock_issue, "stock_issue": stock_issue,
            "missing_sku": sku is None, "reused_sku": reused,
            "duplicate_product_variation_id": duplicate,
            "errors": " | ".join(errors), "warnings": " | ".join(warnings),
        })
    columns = ["row_position", "source_row", "valid", "stock_valid", "stock_issue", "missing_sku",
               "reused_sku", "duplicate_product_variation_id", "errors", "warnings"]
    return {
        "valid": bool(checks) and all(row["valid"] for row in checks),
        "row_count": len(records), "row_checks": pd.DataFrame(checks, columns=columns),
        "stock_as_of": config.stock_as_of,
        "stock_as_of_status": "provided" if config.stock_as_of is not None else "pending_confirmation",
        "stock_definition_status": (
            "confirmed_net_sellable" if config.stock_definition_confirmed
            else "pending_client_confirmation"
        ),
    }


def build_inventory_crosswalk(
    inventory: pd.DataFrame, dim_product: pd.DataFrame, config: InventoryConfig | None = None,
) -> pd.DataFrame:
    """Return one candidate/review row per input row; never approve or combine stock.

    Exact nonblank SKU takes priority. A duplicated SKU candidate or a conflict
    with name evidence cannot silently fall through to a name match. Historical
    pipe-joined SKU alternatives stay review-only. All keys are copied from the
    dimension, never calculated or changed.
    """
    report = validate_current_inventory(inventory, config)
    validate_final_schema(dim_product.columns, "dim_product")
    if dim_product["product_key"].map(_blank).any() or dim_product["product_key"].duplicated().any():
        raise ValueError("Historical product_key must be nonblank and unique")
    added_columns = {
        "product_key", "candidate_product_keys", "match_method", "match_status",
        "mapping_review_required", "review_required", "review_reasons", "reused_sku",
        "stock_valid", "source_row", "stock_as_of", "stock_as_of_status", "stock_definition_status",
    }
    if added_columns.intersection(inventory.columns):
        raise ValueError("Inventory already contains reserved crosswalk columns")
    sku_index, name_index, alias_index = defaultdict(set), defaultdict(set), defaultdict(set)
    for row in dim_product.to_dict("records"):
        key, sku = row["product_key"], _sku(row["SKU"])
        if sku is not None:
            if " | " in sku:
                for token in sku.split(" | "):
                    if not _blank(token):
                        alias_index[token].add(key)
            else:
                sku_index[sku].add(key)
        pair = _name_pair(row["standardized Product Name"], row["standardized Variation Name"])
        if pair is not None:
            name_index[pair].add(key)
    records = inventory.to_dict("records")
    pairs = [_name_pair(r["Product Name"], r["Variation Name"]) for r in records]
    pair_counts = Counter(pair for pair in pairs if pair is not None)
    results = []
    for row, pair, check in zip(records, pairs, report["row_checks"].to_dict("records")):
        sku = _sku(row["SKU"])
        sku_keys, name_keys = sku_index.get(sku, set()), name_index.get(pair, set())
        alias_keys = alias_index.get(sku, set())
        reasons = []
        if sku_keys or alias_keys:
            method = "exact_sku" if sku_keys else "historical_sku_alias_review"
            candidates = sku_keys | alias_keys
            if alias_keys:
                reasons.append("historical_multi_value_sku")
            if sku_keys and name_keys and sku_keys != name_keys:
                reasons.append("sku_name_conflict")
                candidates = candidates | name_keys
        else:
            method = "normalized_name_variation" if name_keys else "none"
            candidates = name_keys
        if check["reused_sku"]:
            reasons.append("reused_sku_stock_pool_unconfirmed")
        if pair is not None and pair_counts[pair] > 1:
            reasons.append("repeated_current_name_pair")
        if len(candidates) > 1:
            reasons.append("multiple_historical_candidates")
        if not candidates:
            reasons.append("unmatched")
        if not check["valid"]:
            reasons.append(check["errors"])
        if pair is None:
            reasons.append("missing_product_or_variation_name")
        safe_candidate = len(candidates) == 1 and not reasons
        status = "candidate" if safe_candidate else ("unmatched" if not candidates else "review_required")
        if report["stock_as_of"] is None:
            reasons.append("stock_as_of_pending_confirmation")
        # Mapping candidates never imply confirmation of physical stock semantics.
        if report["stock_definition_status"] != "confirmed_net_sellable":
            reasons.append("stock_definition_pending_client_confirmation")
        results.append({
            "product_key": next(iter(candidates)) if safe_candidate else pd.NA,
            "candidate_product_keys": " | ".join(sorted(candidates)),
            "match_method": method, "match_status": status,
            "mapping_review_required": not safe_candidate, "review_required": True,
            "review_reasons": " | ".join(reasons), "reused_sku": check["reused_sku"],
            "stock_valid": check["stock_valid"], "source_row": check["source_row"],
            "stock_as_of": report["stock_as_of"], "stock_as_of_status": report["stock_as_of_status"],
            "stock_definition_status": report["stock_definition_status"],
        })
    result = inventory.copy(deep=True)
    for column in sorted(added_columns):
        result[column] = [row[column] for row in results]
    return result
