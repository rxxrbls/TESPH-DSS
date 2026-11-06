"""Conservative cleaning/transform stage for the combined Shopee orders data."""
from __future__ import annotations

import csv
from collections import Counter
from hashlib import sha256
from pathlib import Path
import re
import unicodedata

import pandas as pd

from etl_config import (
    DATE_SOURCE_COLUMNS,
    FINAL_OUTPUT_DIR,
    FINAL_SCHEMAS,
    MEASURE_COLUMNS,
    SOURCE_COLUMN_TYPES,
    TEXT_IDENTIFIER_COLUMNS,
    TEXT_SOURCE_COLUMNS,
)

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "output" / "01_raw_combined.csv"
PROFILE = ROOT / "output" / "02_data_profile.xlsx"
CLEAN_CSV = ROOT / "output" / "03_clean_transactions.csv"
PRODUCT_XLSX = ROOT / "output" / "04_product_master.xlsx"
REPORT_XLSX = ROOT / "output" / "05_cleaning_report.xlsx"
TRACKING_COLUMNS = ("source_file", "source_folder", "source_year")
# These are retained for the historical standalone-cleaning script below. The
# upload path uses the explicit Shopee contract from etl_config instead.
FINANCIAL_TERMS = ("price", "payment", "amount", "total", "discount", "voucher", "fee", "rebate", "shipping", "cashback", "coins offset")
NUMERIC_TERMS = FINANCIAL_TERMS + ("quantity", "weight", "number of items")
REQUIRED_COLUMN_ALIASES = {
    "Order ID": ("Order ID", "Order No"),
    "Product Name": ("Product Name", "Product"),
    "Quantity": ("Quantity",),
    "Order Creation Date": ("Order Creation Date", "Order Created Time"),
}


def extract_file(path: str | Path) -> pd.DataFrame:
    """Extract a CSV/XLSX input without modifying it.

    Shopee workbooks conventionally use an ``orders`` sheet.  If that sheet is
    absent, the workbook's first sheet is used so older exports remain usable.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    suffix = source.suffix.casefold()
    try:
        # Identifier and categorical values must not become numeric simply
        # because a particular monthly export happens to contain digits only.
        # Numeric/date columns are deliberately parsed later by one canonical
        # validator for both input formats.
        source_dtypes = {column: "string" for column in TEXT_SOURCE_COLUMNS}
        if suffix == ".csv":
            try:
                frame = pd.read_csv(source, low_memory=False, dtype=source_dtypes, encoding="utf-8-sig")
            except UnicodeDecodeError:
                frame = pd.read_csv(source, low_memory=False, dtype=source_dtypes, encoding="cp1252")
        elif suffix == ".xlsx":
            # Keep the existing sheet-selection behavior while ensuring the
            # temporary upload can be deleted on Windows after extraction.
            with pd.ExcelFile(source, engine="openpyxl") as workbook:
                orders_sheet = next((s for s in workbook.sheet_names if s.casefold() == "orders"), workbook.sheet_names[0])
                frame = pd.read_excel(workbook, sheet_name=orders_sheet, dtype=source_dtypes)
        else:
            raise ValueError(f"Unsupported file type: {suffix or '<none>'}; expected .csv or .xlsx")
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"Input file is empty: {source}") from exc
    if frame.empty:
        raise ValueError(f"Input file contains no data rows: {source}")
    return frame


def validate_required_columns(df: pd.DataFrame) -> dict[str, str]:
    """Resolve and return required Shopee columns, raising when one is absent."""
    resolved = {
        logical: find_column(df.columns, *aliases)
        for logical, aliases in REQUIRED_COLUMN_ALIASES.items()
    }
    for logical, actual in resolved.items():
        if actual is None:
            raise ValueError(f"Missing required column: {logical}")
    return resolved  # type: ignore[return-value]


def detect_exact_duplicates(df: pd.DataFrame) -> pd.Series:
    """Flag exact transaction duplicates, excluding provenance columns."""
    business_columns = [column for column in df.columns if column not in TRACKING_COLUMNS]
    return df.duplicated(subset=business_columns, keep=False)


def detect_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Return row/column locations of null or blank values without filling them."""
    missing = df.isna().copy()
    for column in df.columns:
        if pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_string_dtype(df[column]):
            missing[column] |= df[column].astype("string").str.strip().eq("").fillna(False)
    rows, columns = missing.to_numpy().nonzero()
    return pd.DataFrame({"row": df.index.to_numpy()[rows], "column": df.columns.to_numpy()[columns]})


def count_missing_values(df: pd.DataFrame) -> int:
    """Count the same missing cells without allocating millions of locations."""
    total = 0
    for column in df.columns:
        values = df[column]
        missing = values.isna()
        if pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values):
            missing |= values.astype("string").str.strip().eq("").fillna(False)
        total += int(missing.sum())
    return total


def parse_datetime_values(values: pd.Series, *, errors: str) -> pd.Series:
    """Parse mixed Shopee datetime strings without pandas inference warnings."""

    return pd.to_datetime(values, errors=errors, format="mixed")


def validate_data_types(df: pd.DataFrame) -> dict[str, object]:
    """Validate parseability without changing source values.

    The returned report is deliberately machine-testable. Legitimate negative
    financial values are reported separately and are not conversion failures.
    """
    invalid: list[dict[str, object]] = []
    negatives: list[dict[str, object]] = []
    # Validate named source fields only.  Arbitrary extra columns are retained
    # for compatibility, but their headings never alter the Shopee contract.
    date_columns = [c for c in DATE_SOURCE_COLUMNS if c in df.columns]
    numeric_columns = [c for c in MEASURE_COLUMNS if c in df.columns]
    for column in date_columns:
        present = nonblank(df[column]) & ~df[column].astype("string").str.strip().eq("-").fillna(False)
        converted = parse_datetime_values(df[column], errors="coerce")
        for index, value in df.loc[present & converted.isna(), column].items():
            invalid.append({"row": index, "column": column, "value": value, "expected_type": "datetime"})
    for column in numeric_columns:
        present = nonblank(df[column])
        converted = pd.to_numeric(df[column], errors="coerce")
        for index, value in df.loc[present & converted.isna(), column].items():
            invalid.append({"row": index, "column": column, "value": value, "expected_type": "numeric"})
        if column not in {"Quantity", "Returned quantity", "SKU Total Weight", "Number of Items in Order", "Order Total Weight"}:
            for index, value in converted[converted.lt(0).fillna(False)].items():
                negatives.append({"row": index, "column": column, "value": value})
    return {
        "valid": not invalid,
        "invalid_values": pd.DataFrame(invalid, columns=["row", "column", "value", "expected_type"]),
        "negative_financial_values": pd.DataFrame(negatives, columns=["row", "column", "value"]),
    }


def transform_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Produce the core derived fields for a valid in-memory transaction frame."""
    columns = validate_required_columns(df)
    report = validate_data_types(df)
    if not report["valid"]:
        issues = report["invalid_values"]
        examples = "; ".join(
            f"row {row.row}, {row.column}={row.value!r} (expected {row.expected_type})"
            for row in issues.head(10).itertuples(index=False)
        )
        raise ValueError(f"Invalid source value(s): {examples}")
    clean = df.copy()
    variation_col = find_column(clean.columns, "Variation Name", "Variation")
    product = clean[columns["Product Name"]].map(standardize_product_value)
    variation = (clean[variation_col].map(standardize_product_value) if variation_col else pd.Series(pd.NA, index=clean.index))
    clean["standardized_product_name"] = product
    clean["standardized_variation_name"] = variation
    clean["product_key"] = [product_key(p, v) for p, v in zip(product, variation)]
    dates = parse_datetime_values(clean[columns["Order Creation Date"]], errors="raise")
    clean["order_date"] = dates.dt.date
    clean["order_year"] = dates.dt.year.astype("Int64")
    clean["order_month"] = dates.dt.month.astype("Int64")
    clean["year_month"] = dates.dt.strftime("%Y-%m").astype("string")
    status_column = find_column(clean.columns, "Order Status")
    return_status_column = find_column(clean.columns, "Return / Refund Status", "Return/Refund Status")
    returned_quantity_column = find_column(clean.columns, "Returned quantity", "Returned Quantity", "Return Quantity")
    statuses = clean[status_column].astype("string").str.strip().str.casefold() if status_column else pd.Series(pd.NA, index=clean.index, dtype="string")
    return_status = clean[return_status_column].astype("string").str.strip().str.casefold() if return_status_column else pd.Series(pd.NA, index=clean.index, dtype="string")
    returned_quantity = pd.to_numeric(clean[returned_quantity_column], errors="coerce") if returned_quantity_column else pd.Series(0, index=clean.index)
    clean["is_completed"] = statuses.eq("completed").fillna(False)
    clean["is_cancelled"] = statuses.str.contains("cancel", na=False)
    clean["is_returned"] = (
        statuses.isin(["returned", "refunded"])
        | returned_quantity.gt(0)
        | return_status.isin(["returned", "refunded", "request approved", "dispute resolved"])
    )
    negative_report = report["negative_financial_values"]
    negative_fields = negative_report.groupby("row")["column"].agg(" | ".join) if not negative_report.empty else pd.Series(dtype="string")
    clean["has_negative_financial_value"] = clean.index.isin(negative_fields.index)
    clean["negative_financial_fields"] = clean.index.to_series().map(negative_fields).astype("string")
    return clean


def validate_final_schema(columns, table_name: str) -> None:
    """Validate the exact frozen column contract for a final ETL table."""
    if table_name not in FINAL_SCHEMAS:
        raise ValueError(f"Unknown final table: {table_name}")
    expected = list(FINAL_SCHEMAS[table_name])
    actual = list(columns)
    missing = [name for name in expected if name not in actual]
    unexpected = [name for name in actual if name not in expected]
    duplicates = [name for name, count in Counter(actual).items() if count > 1]
    if missing or unexpected or duplicates:
        raise ValueError(
            f"Invalid {table_name} schema: missing={missing}; unexpected={unexpected}; duplicate={duplicates}"
        )


def _read_final_csv(path: Path, table_name: str) -> pd.DataFrame:
    expected = list(FINAL_SCHEMAS[table_name])
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"Invalid {table_name} schema: missing={expected}") from exc
        if not header:
            raise ValueError(f"Invalid {table_name} schema: missing={expected}")
        duplicates = [name for name, count in Counter(header).items() if count > 1]
        if duplicates:
            raise ValueError(
                f"Invalid {table_name} schema: missing=[]; unexpected=[]; duplicate={duplicates}"
            )

    dtype = {column: "string" for column in expected if column in TEXT_IDENTIFIER_COLUMNS}
    frame = pd.read_csv(
        path,
        low_memory=False,
        keep_default_na=False,
        na_values=[],
        dtype=dtype,
    )
    frame = frame.apply(lambda column: column.map(lambda value: pd.NA if isinstance(value, str) and not value.strip() else value))
    validate_final_schema(frame.columns, table_name)
    return frame


def load_final_table(table_name: str, output_dir: str | Path = FINAL_OUTPUT_DIR) -> pd.DataFrame:
    """Load one final ETL table after validating the exact schema contract."""
    if table_name not in FINAL_SCHEMAS:
        raise ValueError(f"Unknown final table: {table_name}")
    base = Path(output_dir)
    path = base / f"{table_name}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Final table not found: {path}")
    return _read_final_csv(path, table_name)


def load_prepared_transactions(output_dir: str | Path = FINAL_OUTPUT_DIR) -> pd.DataFrame:
    """Load the finalized transaction handoff for downstream analytics."""
    return load_final_table("prepared_transactions", output_dir)


def load_star_schema(output_dir: str | Path = FINAL_OUTPUT_DIR) -> dict[str, pd.DataFrame]:
    """Load all finalized file-based fact and dimension tables."""
    base = Path(output_dir)
    names = ("fact_sales", "dim_product", "dim_date", "dim_order", "dim_shipping", "dim_payment")
    return {name: load_final_table(name, base) for name in names}


def norm_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def find_column(columns, *aliases):
    lookup = {norm_name(column): column for column in columns}
    return next((lookup[norm_name(alias)] for alias in aliases if norm_name(alias) in lookup), None)


def nonblank(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().ne("")


def standardize_text_value(value):
    if pd.isna(value):
        return pd.NA
    value = unicodedata.normalize("NFKC", str(value))
    if "∩╝" in value:
        value = value.replace("∩╝", "")
        replacement_map = {
            "º": "g",
            "o": "g",
            "í": "a",
            "ñ": "d",
            "Ñ": "e",
            "┤": "t",
        }
        for source, target in replacement_map.items():
            value = value.replace(source, target)
    value = re.sub(r"\s+", " ", value).strip()
    return value if value else pd.NA


def standardize_product_value(value):
    value = standardize_text_value(value)
    return value.casefold() if not pd.isna(value) else pd.NA


def product_key(product, variation) -> str:
    # Versioned, length-framed input prevents ambiguous concatenations. Full
    # SHA-256 keeps the key stable without relying on row order or Python hash().
    p = "<missing-product>" if pd.isna(product) else str(product)
    v = "<no-variation>" if pd.isna(variation) else str(variation)
    payload = f"product-key-v1|{len(p)}:{p}|{len(v)}:{v}".encode("utf-8")
    return "prd_" + sha256(payload).hexdigest()


def joined_unique(series: pd.Series):
    values = sorted({str(value) for value in series if not pd.isna(value) and str(value).strip()})
    return " | ".join(values) if values else pd.NA


def excel_write(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.head(1_048_575).to_excel(writer, sheet_name=name[:31], index=False)
            worksheet = writer.sheets[name[:31]]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cells in worksheet.iter_cols(min_row=1, max_row=min(worksheet.max_row, 250)):
                width = min(max(len(str(cell.value or "")) for cell in cells) + 2, 70)
                worksheet.column_dimensions[cells[0].column_letter].width = width


def main() -> None:
    if not INPUT.is_file():
        raise FileNotFoundError(f"Combined input not found: {INPUT}")
    if not PROFILE.is_file():
        raise FileNotFoundError(f"Profiling report not found: {PROFILE}")

    print(f"Reading: {INPUT}")
    raw = pd.read_csv(INPUT, low_memory=False)
    raw_rows = len(raw)
    original_columns = list(raw.columns)
    product_col = find_column(raw.columns, "Product Name", "Product")
    variation_col = find_column(raw.columns, "Variation Name", "Variation")
    order_col = find_column(raw.columns, "Order ID", "Order No")
    status_col = find_column(raw.columns, "Order Status")
    return_status_col = find_column(raw.columns, "Return / Refund Status", "Return/Refund Status")
    returned_qty_col = find_column(raw.columns, "Returned Quantity", "Return Quantity")
    creation_col = find_column(raw.columns, "Order Creation Date", "Order Created Time")
    sku_col = find_column(raw.columns, "SKU Reference No.", "SKU")
    parent_sku_col = find_column(raw.columns, "Parent SKU Reference No.", "Parent SKU")
    required = {"Product Name": product_col, "Variation Name": variation_col, "Order ID": order_col, "Order Creation Date": creation_col}
    missing_required = [name for name, column in required.items() if column is None]
    if missing_required:
        raise ValueError("Required columns missing: " + ", ".join(missing_required))

    # Confirmed source-level exact duplicates: compare transaction values while
    # excluding provenance. The first identical copy is retained unchanged.
    business_columns = [c for c in raw.columns if c not in TRACKING_COLUMNS]
    exact_all = raw.duplicated(subset=business_columns, keep=False)
    redundant = raw.duplicated(subset=business_columns, keep="first")
    duplicate_groups = int(raw.loc[exact_all, business_columns].drop_duplicates().shape[0])
    removed_audit = raw.loc[redundant, [c for c in ("source_file", "source_folder", order_col, product_col, variation_col, sku_col) if c]].copy()
    removed_audit.insert(0, "removal_reason", "Confirmed source-level exact duplicate; identical retained copy exists")
    clean = raw.loc[~redundant].copy().reset_index(drop=True)

    # Preserve these two source columns exactly; their standardized forms are
    # added separately. Other textual columns receive only conservative trim,
    # Unicode normalization, whitespace collapsing, and blank-to-missing rules.
    protected_originals = {product_col, variation_col}
    text_standardized = 0
    text_details = []
    for column in original_columns:
        if column in protected_originals or not (pd.api.types.is_object_dtype(clean[column]) or pd.api.types.is_string_dtype(clean[column])):
            continue
        before = clean[column].copy()
        after = before.map(standardize_text_value)
        before_compare = before.astype("string").fillna("<NA>")
        after_compare = after.astype("string").fillna("<NA>")
        changed = int(before_compare.ne(after_compare).sum())
        clean[column] = after
        text_standardized += changed
        text_details.append({"column": column, "values_standardized": changed})

    clean["standardized_product_name"] = clean[product_col].map(standardize_product_value)
    clean["standardized_variation_name"] = clean[variation_col].map(standardize_product_value)
    clean["product_key"] = [product_key(p, v) for p, v in zip(clean["standardized_product_name"], clean["standardized_variation_name"])]
    product_standardization_changes = int(
        clean[product_col].astype("string").fillna("<NA>").ne(clean["standardized_product_name"].astype("string").fillna("<NA>")).sum()
        + clean[variation_col].astype("string").fillna("<NA>").ne(clean["standardized_variation_name"].astype("string").fillna("<NA>")).sum()
    )

    conversion_rows = []
    date_conversions = 0
    date_missing_markers = 0
    date_columns = [c for c in original_columns if re.search(r"date|time", str(c), flags=re.I)]
    for column in date_columns:
        # Shopee uses a lone dash as a missing date marker in some exports.
        # It carries no business/date value, so normalize it to missing before
        # parsing rather than treating it as an invented or corrected date.
        placeholder = clean[column].astype("string").str.strip().eq("-").fillna(False)
        placeholder_count = int(placeholder.sum())
        if placeholder_count:
            clean.loc[placeholder, column] = pd.NA
            date_missing_markers += placeholder_count
        present = nonblank(clean[column])
        converted = parse_datetime_values(clean[column], errors="coerce")
        successful = int((present & converted.notna()).sum())
        failed = int((present & converted.isna()).sum())
        clean[column] = converted
        date_conversions += successful
        conversion_rows.append({"conversion_type": "datetime", "column": column, "source_missing_markers_standardized": placeholder_count, "nonblank_input": int(present.sum()), "successfully_converted": successful, "coerced_to_missing": failed})

    numeric_conversions = 0
    numeric_columns = []
    for column in original_columns:
        lowered = str(column).casefold()
        if not any(term in lowered for term in NUMERIC_TERMS):
            continue
        present = nonblank(clean[column])
        candidate = pd.to_numeric(clean[column], errors="coerce")
        success_rate = float((present & candidate.notna()).sum() / max(int(present.sum()), 1))
        # Avoid fields such as "Shipping Option"; requested financial/quantity
        # fields parse overwhelmingly as numeric in valid exports.
        if success_rate < 0.80:
            continue
        successful = int((present & candidate.notna()).sum())
        failed = int((present & candidate.isna()).sum())
        clean[column] = candidate
        numeric_columns.append(column)
        numeric_conversions += successful
        conversion_rows.append({"conversion_type": "numeric", "column": column, "nonblank_input": int(present.sum()), "successfully_converted": successful, "coerced_to_missing": failed})

    # Negative signs remain unchanged. Flags make them reviewable.
    financial_columns = [c for c in numeric_columns if any(term in str(c).casefold() for term in FINANCIAL_TERMS)]
    negative_by_column = []
    negative_masks = {}
    for column in financial_columns:
        mask = clean[column].lt(0).fillna(False)
        negative_masks[column] = mask
        if mask.any():
            negative_by_column.append({"column": column, "negative_value_count": int(mask.sum()), "minimum_value": clean[column].min()})
    if negative_masks:
        clean["has_negative_financial_value"] = pd.DataFrame(negative_masks).any(axis=1)
        clean["negative_financial_fields"] = [" | ".join(c for c, mask in negative_masks.items() if mask.iat[i]) or pd.NA for i in range(len(clean))]
    else:
        clean["has_negative_financial_value"] = False
        clean["negative_financial_fields"] = pd.NA
    negative_rows = int(clean["has_negative_financial_value"].sum())

    order_dates = clean[creation_col]
    clean["order_date"] = order_dates.dt.date
    clean["order_year"] = order_dates.dt.year.astype("Int64")
    clean["order_month"] = order_dates.dt.month.astype("Int64")
    clean["year_month"] = order_dates.dt.strftime("%Y-%m").astype("string")
    statuses = clean[status_col].astype("string").str.strip().str.casefold() if status_col else pd.Series(pd.NA, index=clean.index, dtype="string")
    clean["is_completed"] = statuses.eq("completed").fillna(False)
    clean["is_cancelled"] = statuses.str.contains("cancel", na=False)
    return_status = clean[return_status_col].astype("string").str.strip().str.casefold() if return_status_col else pd.Series(pd.NA, index=clean.index, dtype="string")
    returned_qty = pd.to_numeric(clean[returned_qty_col], errors="coerce") if returned_qty_col else pd.Series(0, index=clean.index)
    clean["is_returned"] = (
        statuses.isin(["returned", "refunded"])
        | returned_qty.gt(0)
        | return_status.isin(["returned", "refunded", "request approved", "dispute resolved"])
    )

    # Re-evaluate line candidates after removing only confirmed exact copies.
    possible_keys = list(dict.fromkeys(c for c in (order_col, product_col, sku_col, variation_col) if c))
    possible_mask = nonblank(clean[order_col]) & clean.duplicated(subset=possible_keys, keep=False)
    possible_retained = int(possible_mask.sum())
    possible_groups = int(clean.loc[possible_mask, possible_keys].drop_duplicates().shape[0])

    master = clean.groupby("product_key", sort=True, dropna=False).agg(**{
        "original Product Name": pd.NamedAgg(column=product_col, aggfunc=joined_unique),
        "standardized Product Name": pd.NamedAgg(column="standardized_product_name", aggfunc="first"),
        "original Variation Name": pd.NamedAgg(column=variation_col, aggfunc=joined_unique),
        "standardized Variation Name": pd.NamedAgg(column="standardized_variation_name", aggfunc="first"),
        "Parent SKU": pd.NamedAgg(column=parent_sku_col, aggfunc=joined_unique) if parent_sku_col else pd.NamedAgg(column=product_col, aggfunc=lambda _: pd.NA),
        "SKU": pd.NamedAgg(column=sku_col, aggfunc=joined_unique) if sku_col else pd.NamedAgg(column=product_col, aggfunc=lambda _: pd.NA),
    }).reset_index()
    master["category"] = pd.NA
    master["category_mapping_status"] = "Needs Review"
    missing_master_parent = int(master["Parent SKU"].isna().sum())
    missing_master_sku = int(master["SKU"].isna().sum())

    clean.to_csv(CLEAN_CSV, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")
    excel_write(PRODUCT_XLSX, {"Product_Master": master})

    overview = pd.DataFrame([
        ("Raw row count", raw_rows), ("Cleaned row count", len(clean)),
        ("Confirmed exact duplicate groups", duplicate_groups), ("Exact duplicate rows removed", int(redundant.sum())),
        ("Possible duplicate transaction lines retained", possible_retained), ("Possible duplicate groups retained", possible_groups),
        ("Text values standardized", text_standardized + product_standardization_changes + date_missing_markers),
        ("Date placeholder markers standardized to missing", date_missing_markers),
        ("Date values safely converted", date_conversions), ("Numeric values safely converted", numeric_conversions),
        ("Rows flagged for negative financial values", negative_rows), ("Products in Product Master", len(master)),
        ("Products with missing Parent SKU", missing_master_parent), ("Products with missing SKU", missing_master_sku),
    ], columns=["metric", "value"])
    transformations = pd.DataFrame([
        ("Exact deduplication", "Removed only redundant copies identical across all transaction columns; source tracking excluded; kept first identical copy"),
        ("Text", "NFKC Unicode normalization, trim, collapse whitespace, blank strings to missing; original Product Name and Variation Name preserved"),
        ("Product standardization", "Added casefolded standardized product/variation fields; no correction of business wording"),
        ("product_key", "SHA-256 of versioned, length-framed standardized Product Name + Variation Name; independent of row order"),
        ("Dates", "Safely parsed columns whose names contain Date or Time; invalid nonblank values coerced to missing and reported"),
        ("Numerics", "Safely parsed quantity/weight and financial columns with >=80% parse rate; failures coerced to missing and reported"),
        ("Negative financials", "Signs preserved; added has_negative_financial_value and negative_financial_fields"),
        ("Derived dates", "Added order_date, order_year, order_month, and year_month from Order Creation Date"),
        ("is_completed", "True only when normalized Order Status equals Completed"),
        ("is_cancelled", "True when normalized Order Status contains cancel"),
        ("is_returned", "True when Returned Quantity > 0 or Return/Refund Status is Request Approved or Dispute Resolved"),
        ("Categories", "Left category blank and set category_mapping_status to Needs Review"),
    ], columns=["transformation", "rule"])
    unresolved = pd.DataFrame([
        ("Possible duplicate transaction lines", possible_retained, "Retained; not confirmed exact duplicates"),
        ("Source date placeholder markers", date_missing_markers, "Lone '-' values carried no date and were standardized to missing"),
        ("Missing Parent SKU in Product Master", missing_master_parent, "Retained; no values fabricated"),
        ("Missing SKU in Product Master", missing_master_sku, "Retained; no values fabricated"),
        ("Negative financial rows", negative_rows, "Values and signs retained; anomaly flags added"),
        ("Category assignments", len(master), "All require review; no categories assigned"),
    ], columns=["issue", "count", "handling"])
    excel_write(REPORT_XLSX, {
        "Overview": overview, "Transformations": transformations,
        "Column_Conversions": pd.DataFrame(conversion_rows),
        "Text_Standardization": pd.DataFrame(text_details),
        "Negative_Flags": pd.DataFrame(negative_by_column),
        "Removed_Duplicates": removed_audit, "Unresolved_Issues": unresolved,
    })

    print("\nCleaning and transformation complete.")
    for metric, value in overview.itertuples(index=False, name=None):
        print(f"{metric}: {value:,}" if isinstance(value, int) else f"{metric}: {value}")
    print(f"Clean transactions: {CLEAN_CSV}")
    print(f"Product master: {PRODUCT_XLSX}")
    print(f"Cleaning report: {REPORT_XLSX}")


if __name__ == "__main__":
    main()
