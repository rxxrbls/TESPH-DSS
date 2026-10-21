"""Create the final Member 1 handoff datasets and validation report.

Reads finalized outputs without modifying them and writes only final_outputs/.
"""
from pathlib import Path
import hashlib
import re

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
if not OUT.is_dir():
    OUT = ROOT / "working_outputs_archive" / "output"
FINAL = ROOT / "final_outputs"
TRANSACTIONS = OUT / "03_clean_transactions.csv"
PRODUCT_MASTER = OUT / "04_product_master.xlsx"
FINAL_NAMES = OUT / "10C_product_name_variation_review.xlsx"
FINAL_CATEGORIES = OUT / "14_final_category_mapping.xlsx"
RAW_COMBINED = OUT / "01_raw_combined.csv"

EXPECTED = {
    "raw_rows": 226_205,
    "final_rows": 226_203,
    "duplicates_removed": 2,
    "base_products": 713,
    "product_keys": 2_116,
    "categories": 20,
}

SHIPPING_FIELDS = [
    "Tracking Number*", "Shipping Option", "Shipment Method", "Receiver Name", "Phone Number",
    "Delivery Address", "Town", "District", "City", "Province", "Country", "Zip Code",
]
PAYMENT_FIELDS = ["Hot Listing", "Bundle Deals Indicator(Y/N)", "Invoice request type", "Invoice type"]
ORDER_FIELDS = [
    "Order Status", "Cancel reason", "Return / Refund Status", "Estimated Ship Out Date", "Ship Time",
    "Order Creation Date", "Order Paid Time", "Order Complete Time", "Username (Buyer)",
    "Remark from buyer", "Note", "Number of Items in Order", "Order Total Weight",
    "Business number", "Name", "Address",
]
MEASURE_FIELDS = [
    "Quantity", "Returned quantity", "Original Price", "Deal Price", "Total Buyer Payment",
    "Total Discount(PHP)", "Price Discount(from Seller)(PHP)", "Shopee Rebate(PHP)",
    "SKU Total Weight", "Number of Items in Order", "Order Total Weight", "Seller Voucher(PHP)",
    "Coin Cashback Voucher Amount Sponsored by Seller", "Shopee Voucher(PHP)",
    "Shopee Bundle Discount(PHP)", "Seller Bundle Discount(PHP)", "Shopee Coins Offset(PHP)",
    "Credit Card Discount Total(PHP)", "Products' Price Paid by Buyer (PHP)",
    "Buyer Paid Shipping Fee", "Shipping Rebate Estimate", "Reverse Shipping Fee", "Service Fee",
    "Grand Total", "Estimated Shipping Fee",
]


def canonical(value):
    if pd.isna(value):
        return "<NA>"
    return re.sub(r"\s+", " ", str(value)).strip()


def stable_hash(prefix, values):
    payload = "\x1f".join(canonical(value) for value in values)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def frame_keys(frame, columns, prefix):
    # Avoid constructing an Arrow-backed Series for every source row. Materialize
    # the common row representation once; keep the hash payload unchanged.
    values = frame[columns].to_numpy()
    if pd.api.types.is_datetime64_any_dtype(values.dtype):
        values = frame[columns].to_numpy(dtype=object)
    return pd.Series([stable_hash(prefix, row) for row in values], index=frame.index)


def unique_source_values(series):
    values = sorted({canonical(x) for x in series if not pd.isna(x) and canonical(x) != ""}, key=lambda x: (x.casefold(), x))
    return " | ".join(values) if values else pd.NA


def nonblank(series):
    return series.notna() & series.astype("string").str.strip().ne("")


def count_csv_rows(path):
    # CSV fields may legally contain embedded line breaks, so physical line
    # counting is not a valid record count. Parse in chunks without retaining
    # the 118 MB raw dataset in memory.
    return sum(len(chunk) for chunk in pd.read_csv(path, chunksize=50_000, low_memory=False))


def load_product_bridge():
    master = pd.read_excel(PRODUCT_MASTER, sheet_name="Product_Master", engine="openpyxl")
    names = pd.read_excel(FINAL_NAMES, sheet_name="Final_Base_Product_Names", engine="openpyxl")
    categories = pd.read_excel(FINAL_CATEGORIES, sheet_name="Final_Category_Mapping", engine="openpyxl")

    name_bridge = names[["original_sample_shopee_product_name", "final_base_product_name"]]
    category_bridge = categories[[
        "standardized_product_name", "original_sample_shopee_product_name", "final_category",
        "category_mapping_status", "category_mapping_source",
    ]]
    base = category_bridge.merge(name_bridge, on="original_sample_shopee_product_name", how="left", validate="one_to_one")
    if len(base) != EXPECTED["base_products"] or base[["final_base_product_name", "final_category"]].isna().any().any():
        raise ValueError("Final name/category bridge failed validation")

    product = master.merge(
        base[["standardized_product_name", "final_base_product_name", "final_category", "category_mapping_status", "category_mapping_source"]],
        left_on="standardized Product Name", right_on="standardized_product_name", how="left", validate="many_to_one",
    )
    product = product.drop(columns=["standardized_product_name", "category", "category_mapping_status_x"], errors="ignore").rename(
        columns={"category_mapping_status_y": "category_mapping_status"}
    )
    required = ["product_key", "final_base_product_name", "final_category"]
    if product[required].isna().any().any() or product["product_key"].duplicated().any():
        raise ValueError("Final Product Master has missing or duplicate analytical keys")
    return product, base


def create_product_master(product, save_to_disk=True):
    final_master = product[[
        "product_key", "original Product Name", "original Variation Name", "final_base_product_name",
        "standardized Product Name", "standardized Variation Name", "Parent SKU", "SKU", "final_category",
        "category_mapping_status", "category_mapping_source",
    ]].copy()
    if save_to_disk:
        final_master.to_excel(FINAL / "product_master_final.xlsx", sheet_name="Product_Master", index=False, engine="openpyxl")
    return final_master


def create_prepared(product, transactions=None, save_to_disk=True):
    if transactions is None:
        transactions = pd.read_csv(TRANSACTIONS, low_memory=False)
    bridge = product[["product_key", "final_base_product_name", "final_category"]]
    prepared = transactions.merge(bridge, on="product_key", how="left", validate="many_to_one", indicator="_product_match")
    unmatched = prepared[prepared["_product_match"].ne("both")].copy()
    prepared = prepared.drop(columns="_product_match")
    if save_to_disk:
        prepared.to_csv(FINAL / "prepared_transactions.csv", index=False, encoding="utf-8-sig")
    return transactions, prepared, unmatched


def create_dim_product(final_master):
    return final_master[[
        "product_key", "original Product Name", "original Variation Name", "final_base_product_name",
        "standardized Product Name", "standardized Variation Name", "Parent SKU", "SKU", "final_category",
    ]].copy()


def create_dim_date(prepared):
    dates = pd.to_datetime(prepared["order_date"], errors="coerce").dropna().dt.normalize().drop_duplicates().sort_values()
    dim = pd.DataFrame({"full_date": dates})
    dim["date_key"] = dim["full_date"].dt.strftime("%Y%m%d").astype("int64")
    dim["year"] = dim["full_date"].dt.year
    dim["quarter"] = "Q" + dim["full_date"].dt.quarter.astype(str)
    dim["month_number"] = dim["full_date"].dt.month
    dim["month_name"] = dim["full_date"].dt.month_name()
    dim["year_month"] = dim["full_date"].dt.strftime("%Y-%m")
    dim["day"] = dim["full_date"].dt.day
    dim["day_of_week"] = dim["full_date"].dt.day_name()
    return dim[["date_key", "full_date", "year", "quarter", "month_number", "month_name", "year_month", "day", "day_of_week"]]


def create_dim_order(prepared):
    work = prepared[["Order ID"] + ORDER_FIELDS].copy()
    for field in ORDER_FIELDS:
        work[field] = work[field].astype("string").str.strip().replace("", pd.NA)
    grouped = work.groupby("Order ID", sort=True, dropna=False)
    result = grouped[ORDER_FIELDS].first()
    counts = grouped[ORDER_FIELDS].nunique(dropna=True)
    # Only conflicting order/field combinations need the more expensive joined
    # representation. Nonconflicting values are already preserved by first().
    for field in ORDER_FIELDS:
        conflicting_orders = counts.index[counts[field].gt(1)]
        if len(conflicting_orders):
            joined = work[work["Order ID"].isin(conflicting_orders)].groupby("Order ID", dropna=False)[field].agg(unique_source_values)
            result.loc[joined.index, field] = joined
    conflict_lists = pd.Series(
        [" | ".join(field for field, conflict in zip(ORDER_FIELDS, row) if conflict)
         for row in counts.gt(1).to_numpy()], index=counts.index,
    )
    result["has_order_attribute_conflict"] = conflict_lists.ne("")
    result["conflicting_order_attributes"] = conflict_lists.replace("", pd.NA)
    return result.reset_index()


def create_context_dimension(prepared, fields, key_name, prefix):
    work = prepared[fields].copy()
    work[key_name] = frame_keys(work, fields, prefix)
    return work[[key_name] + fields].drop_duplicates(subset=[key_name]).sort_values(key_name).reset_index(drop=True)


def create_fact(prepared, dim_date):
    fact = pd.DataFrame(index=prepared.index)
    # A row-content hash plus occurrence counter remains deterministic even if
    # separately legitimate identical-looking lines exist within one order.
    hash_columns = ["Order ID", "product_key", "source_file", "Order Creation Date", "Quantity", "Deal Price", "Grand Total"]
    bases = frame_keys(prepared, hash_columns, "line_")
    occurrences = bases.groupby(bases).cumcount().astype(str)
    fact["sales_line_key"] = [stable_hash("sale_", [base, occurrence]) for base, occurrence in zip(bases, occurrences)]
    fact["Order ID"] = prepared["Order ID"]
    fact["product_key"] = prepared["product_key"]
    order_dates = pd.to_datetime(prepared["order_date"], errors="coerce")
    fact["date_key"] = pd.to_numeric(order_dates.dt.strftime("%Y%m%d"), errors="coerce").astype("Int64")
    fact["shipping_key"] = frame_keys(prepared, SHIPPING_FIELDS, "shp_")
    fact["payment_key"] = frame_keys(prepared, PAYMENT_FIELDS, "pay_")
    for field in MEASURE_FIELDS:
        fact[field] = prepared[field]
    for field in ["has_negative_financial_value", "negative_financial_fields", "is_completed", "is_cancelled", "is_returned", "source_file", "source_folder"]:
        fact[field] = prepared[field]
    return fact


DESCRIPTIONS = {
    "product_key": "Stable deterministic identifier for a product and variation.",
    "final_base_product_name": "Final concise analytical label for the base product.",
    "final_category": "Final controlled analytical product category.",
    "sales_line_key": "Deterministic unique identifier for a cleaned transaction line.",
    "date_key": "Calendar date surrogate key in YYYYMMDD format.",
    "full_date": "Complete transaction calendar date.",
    "shipping_key": "Deterministic key for the available shipping and destination context.",
    "payment_key": "Deterministic key for available payment/invoice descriptors; monetary values remain in fact_sales.",
    "has_order_attribute_conflict": "True when an Order ID has multiple nonblank values for an expected order-level field.",
    "conflicting_order_attributes": "Pipe-delimited list of order-level fields containing conflicting source values.",
    "Quantity": "Quantity sold on the transaction line.",
    "Returned quantity": "Quantity returned for the transaction line.",
    "final_base_product_name": "Final concise analytical base-product name; Variation Name remains separate.",
}


def source_field_for(field):
    derived = {
        "product_key", "final_base_product_name", "final_category", "sales_line_key",
        "date_key", "full_date", "year", "quarter", "month_number", "month_name", "year_month",
        "day", "day_of_week", "shipping_key", "payment_key", "has_order_attribute_conflict",
        "conflicting_order_attributes", "source_file", "source_folder", "has_negative_financial_value",
        "negative_financial_fields", "order_date", "order_year", "order_month", "is_completed",
        "is_cancelled", "is_returned", "category_mapping_status", "category_mapping_source",
    }
    direct_source = {
        "Product Name": "Product Name", "Variation Name": "Variation Name",
        "original Product Name": "Product Name", "original Variation Name": "Variation Name",
    }
    source_aliases = {"Parent SKU": "Parent SKU Reference No.", "SKU": "SKU Reference No."}
    if field in derived:
        return "Derived", pd.NA
    if field in direct_source:
        return "Source", direct_source[field]
    return "Cleaned Source", source_aliases.get(field, field)


def dictionary_sheet(frame):
    rows = []
    for field in frame.columns:
        source_type, original = source_field_for(field)
        examples = frame[field].dropna().astype(str).drop_duplicates().head(3).tolist()
        description = DESCRIPTIONS.get(field, field.replace("_", " ").replace("(PHP)", " in PHP").strip().capitalize() + ".")
        notes = "Preserves original monetary sign." if field in MEASURE_FIELDS and any(word in field.casefold() for word in ("price", "payment", "discount", "rebate", "fee", "total", "voucher", "coins")) else pd.NA
        rows.append({
            "field_name": field, "description": description, "source_or_derived": source_type,
            "original_source_field": original, "data_type": str(frame[field].dtype),
            "example/allowed values": " | ".join(examples), "notes": notes,
        })
    return pd.DataFrame(rows)


def shopee_source_dictionary(transactions):
    """Document only the 60 columns supplied by the original Shopee exports."""
    etl_columns = {
        "source_file", "source_folder", "source_year", "standardized_product_name",
        "standardized_variation_name", "product_key", "has_negative_financial_value",
        "negative_financial_fields", "order_date", "order_year", "order_month",
        "year_month", "is_completed", "is_cancelled", "is_returned",
    }
    fields = [field for field in transactions.columns if field not in etl_columns]
    if len(fields) != 60:
        raise ValueError(f"Expected 60 original Shopee source fields; found {len(fields)}")
    result = dictionary_sheet(transactions[fields])
    result["source_or_derived"] = "Source"
    result["original_source_field"] = result["field_name"]
    return result


def make_validation(raw_rows, transactions, prepared, unmatched, base, product, final_master, dims, fact):
    dim_product, dim_date, dim_order, dim_shipping, dim_payment = dims
    exact_remaining = int(prepared.duplicated().sum())
    unique_orders = int(prepared["Order ID"].nunique(dropna=True))
    quantity_source = pd.to_numeric(transactions["Quantity"], errors="coerce").sum(min_count=1)
    quantity_prepared = pd.to_numeric(prepared["Quantity"], errors="coerce").sum(min_count=1)
    retained_source_fields = [field for field in transactions.columns if field not in {"standardized_product_name", "standardized_variation_name"}]
    source_hash = pd.util.hash_pandas_object(transactions[retained_source_fields], index=False)
    prepared_hash = pd.util.hash_pandas_object(prepared[retained_source_fields], index=False)
    changed_transaction_rows = int(source_hash.ne(prepared_hash).sum())

    name_by_key_max = int(final_master.groupby("product_key")["final_base_product_name"].nunique().max())
    direct_names = pd.read_excel(FINAL_NAMES, sheet_name="Final_Base_Product_Names", engine="openpyxl")[["original_sample_shopee_product_name", "final_base_product_name"]]
    expected_base_names = base[["standardized_product_name", "original_sample_shopee_product_name"]].merge(
        direct_names, on="original_sample_shopee_product_name", how="left", validate="one_to_one"
    )
    expected_name_map = expected_base_names.set_index("standardized_product_name")["final_base_product_name"]
    expected_product_names = product["standardized Product Name"].map(expected_name_map)
    names_not_direct_from_10c = int(product["final_base_product_name"].astype("string").ne(expected_product_names.astype("string")).sum())
    category_actual = prepared.groupby("final_category", dropna=False).agg(
        transaction_count=("product_key", "size"), total_quantity_sold=("Quantity", lambda x: pd.to_numeric(x, errors="coerce").sum())
    ).reset_index()
    category_expected = pd.read_excel(FINAL_CATEGORIES, sheet_name="Final_Category_Summary", engine="openpyxl")[["category", "transaction_count", "total_quantity_sold"]]
    category_recon = category_expected.merge(category_actual, left_on="category", right_on="final_category", how="outer", suffixes=("_expected", "_actual"))
    category_recon["transaction_difference"] = category_recon["transaction_count_actual"].fillna(0) - category_recon["transaction_count_expected"].fillna(0)
    category_recon["quantity_difference"] = category_recon["total_quantity_sold_actual"].fillna(0) - category_recon["total_quantity_sold_expected"].fillna(0)
    category_recon["status"] = ((category_recon["transaction_difference"] == 0) & (category_recon["quantity_difference"].abs() < 1e-9)).map({True: "PASS", False: "FAIL"})

    duplicate_checks = {
        "dim_product.product_key": int(dim_product["product_key"].duplicated().sum()),
        "dim_date.date_key": int(dim_date["date_key"].duplicated().sum()),
        "dim_order.Order ID": int(dim_order["Order ID"].duplicated().sum()),
        "dim_shipping.shipping_key": int(dim_shipping["shipping_key"].duplicated().sum()),
        "dim_payment.payment_key": int(dim_payment["payment_key"].duplicated().sum()),
        "fact_sales.sales_line_key": int(fact["sales_line_key"].duplicated().sum()),
    }
    orphan_checks = {
        "fact product_key not in dim_product": int((~fact["product_key"].isin(dim_product["product_key"])).sum()),
        "fact date_key not in dim_date": int((fact["date_key"].notna() & ~fact["date_key"].isin(dim_date["date_key"])).sum()),
        "fact Order ID not in dim_order": int((~fact["Order ID"].isin(dim_order["Order ID"])).sum()),
        "fact shipping_key not in dim_shipping": int((~fact["shipping_key"].isin(dim_shipping["shipping_key"])).sum()),
        "fact payment_key not in dim_payment": int((~fact["payment_key"].isin(dim_payment["payment_key"])).sum()),
    }
    validations = [
        ("Raw combined rows", EXPECTED["raw_rows"], raw_rows),
        ("Final transactions", EXPECTED["final_rows"], len(prepared)),
        ("Redundant exact duplicates removed", EXPECTED["duplicates_removed"], raw_rows - len(prepared)),
        ("Exact duplicate prepared rows remaining", 0, exact_remaining),
        ("Transactions missing product_key", 0, int((~nonblank(prepared["product_key"])).sum())),
        ("Transactions missing final_base_product_name", 0, int((~nonblank(prepared["final_base_product_name"])).sum())),
        ("Transactions missing final_category", 0, int((~nonblank(prepared["final_category"])).sum())),
        ("Unmatched product joins", 0, len(unmatched)),
        ("Base products", EXPECTED["base_products"], len(base)),
        ("Product variations/product keys", EXPECTED["product_keys"], len(final_master)),
        ("Unique product_key count", EXPECTED["product_keys"], int(final_master["product_key"].nunique())),
        ("Maximum final names per product_key", 1, name_by_key_max),
        ("Final names differing from file 10C", 0, names_not_direct_from_10c),
        ("Final categories", EXPECTED["categories"], int(base["final_category"].nunique())),
        ("Unique orders", unique_orders, unique_orders),
        ("Quantity total reconciliation", quantity_source, quantity_prepared),
        ("Rows with changed retained transaction values", 0, changed_transaction_rows),
        ("Category reconciliation failures", 0, int(category_recon["status"].eq("FAIL").sum())),
        ("Duplicate dimension/fact keys", 0, sum(duplicate_checks.values())),
        ("Orphan fact foreign keys", 0, sum(orphan_checks.values())),
    ]
    overview = pd.DataFrame(validations, columns=["validation", "expected", "actual"])
    overview["status"] = overview.apply(lambda r: "PASS" if (pd.isna(r.expected) and pd.isna(r.actual)) or r.expected == r.actual else "FAIL", axis=1)
    dimension_validation = pd.DataFrame([{"key_check": key, "duplicate_count": value, "status": "PASS" if value == 0 else "FAIL"} for key, value in duplicate_checks.items()])
    orphan_validation = pd.DataFrame([{"orphan_check": key, "orphan_count": value, "status": "PASS" if value == 0 else "FAIL"} for key, value in orphan_checks.items()])
    order_conflicts = dim_order[dim_order["has_order_attribute_conflict"]].copy()
    flags = pd.DataFrame([
        {"data_quality_flag": "Rows with negative financial values", "row_count": int(prepared["has_negative_financial_value"].astype(str).str.casefold().isin(["true", "1", "yes"]).sum()), "treatment": "Retained; original signs preserved"},
        {"data_quality_flag": "Rows with unparseable order_date", "row_count": int(pd.to_datetime(prepared["order_date"], errors="coerce").isna().sum()), "treatment": "Retained and reported"},
        {"data_quality_flag": "Orders with conflicting order-level attributes", "row_count": len(order_conflicts), "treatment": "All distinct values retained and conflict flagged"},
        {"data_quality_flag": "Unmatched final analytical product records", "row_count": len(unmatched), "treatment": "Reported; no guessing"},
    ])
    approved_examples = [
        "Reusable Waterproof Poncho", "500 Pcs Thank You Sticker Roll", "Tap Water Faucet Filter",
        "3x3 Magnetic Rubix Cube", "Needoh Luminescent Ball",
        "Portable Butane Gas Stove with BBQ Skewer Griller Set & Case",
        "Portable Butane Gas Stove with BBQ Skewer Griller Set",
    ]
    example_check = pd.DataFrame({"expected_final_base_product_name": approved_examples})
    example_check["occurrence_count_in_product_master"] = example_check["expected_final_base_product_name"].map(final_master["final_base_product_name"].value_counts()).fillna(0).astype(int)
    example_check["status"] = example_check["occurrence_count_in_product_master"].gt(0).map({True: "PASS", False: "FAIL"})
    return overview, category_recon, dimension_validation, orphan_validation, order_conflicts, flags, example_check


def write_excel(path, sheets):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            sheet = writer.sheets[name[:31]]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.iter_cols(min_row=1, max_row=min(sheet.max_row, 400)):
                sheet.column_dimensions[cells[0].column_letter].width = min(max(len(str(c.value or "")) for c in cells) + 2, 70)


def build_star_schema_tables(transformed: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build all star schema tables from a transformed DataFrame.
    
    Returns dict with keys: fact_sales, dim_product, dim_date,
    dim_order, dim_shipping, dim_payment, prepared_transactions.
    """
    # Upload processing must be self-contained.  The legacy build path above
    # reads archived intermediate workbooks, which are not part of a user
    # upload and made a valid monthly Shopee export fail.  Build its product
    # grain from the current transformed upload, then optionally apply only
    # existing governed labels/categories by the deterministic product key.
    required = [
        "product_key", "Product Name", "Variation Name", "standardized_product_name",
        "standardized_variation_name", "Parent SKU Reference No.", "SKU Reference No.",
    ]
    missing = [column for column in required if column not in transformed.columns]
    if missing:
        raise ValueError("Cannot build product dimension; missing source fields: " + ", ".join(missing))
    product = transformed[required].copy()
    product = product.rename(columns={
        "Product Name": "original Product Name",
        "Variation Name": "original Variation Name",
        "standardized_product_name": "standardized Product Name",
        "standardized_variation_name": "standardized Variation Name",
        "Parent SKU Reference No.": "Parent SKU",
        "SKU Reference No.": "SKU",
    })
    product = product.drop_duplicates("product_key", keep="first")
    product["final_base_product_name"] = product["original Product Name"]
    product["final_category"] = pd.NA

    # This file is a governed product/category reference, never a replacement
    # transaction source. New/renamed products deliberately remain unmapped
    # so downstream eligibility can require business-owner review.
    reference_path = FINAL / "dim_product.csv"
    if reference_path.is_file():
        reference = pd.read_csv(reference_path, dtype="string", usecols=lambda c: c in {"product_key", "final_base_product_name", "final_category"})
        if {"product_key", "final_base_product_name", "final_category"}.issubset(reference.columns):
            reference = reference.drop_duplicates("product_key", keep="last").rename(columns={
                "final_base_product_name": "_governed_name", "final_category": "_governed_category",
            })
            product = product.merge(reference, on="product_key", how="left", validate="one_to_one")
            product["final_base_product_name"] = product["_governed_name"].fillna(product["final_base_product_name"])
            product["final_category"] = product["_governed_category"]
            product = product.drop(columns=["_governed_name", "_governed_category"])

    final_master = product[[
        "product_key", "original Product Name", "original Variation Name", "final_base_product_name",
        "standardized Product Name", "standardized Variation Name", "Parent SKU", "SKU", "final_category",
    ]].copy()
    _, prepared, _ = create_prepared(final_master, transactions=transformed, save_to_disk=False)
    
    dim_product = create_dim_product(final_master)
    dim_date = create_dim_date(prepared)
    dim_order = create_dim_order(prepared)
    dim_shipping = create_context_dimension(prepared, SHIPPING_FIELDS, "shipping_key", "shp_")
    dim_payment = create_context_dimension(prepared, PAYMENT_FIELDS, "payment_key", "pay_")
    fact = create_fact(prepared, dim_date)
    
    return {
        "fact_sales": fact,
        "dim_product": dim_product,
        "dim_date": dim_date,
        "dim_order": dim_order,
        "dim_shipping": dim_shipping,
        "dim_payment": dim_payment,
        "prepared_transactions": prepared,
    }


def main():
    for path in (TRANSACTIONS, PRODUCT_MASTER, FINAL_NAMES, FINAL_CATEGORIES, RAW_COMBINED):
        if not path.is_file():
            raise FileNotFoundError(path)
    FINAL.mkdir(exist_ok=True)

    print("Reconciling finalized product names, categories, and product keys...")
    product, base = load_product_bridge()
    final_master = create_product_master(product)
    transactions, prepared, unmatched = create_prepared(product)

    print("Building star-schema tables...")
    dim_product = create_dim_product(final_master)
    dim_date = create_dim_date(prepared)
    dim_order = create_dim_order(prepared)
    dim_shipping = create_context_dimension(prepared, SHIPPING_FIELDS, "shipping_key", "shp_")
    dim_payment = create_context_dimension(prepared, PAYMENT_FIELDS, "payment_key", "pay_")
    fact = create_fact(prepared, dim_date)
    tables = {
        "fact_sales.csv": fact, "dim_product.csv": dim_product, "dim_date.csv": dim_date,
        "dim_order.csv": dim_order, "dim_shipping.csv": dim_shipping, "dim_payment.csv": dim_payment,
    }
    for filename, frame in tables.items():
        frame.to_csv(FINAL / filename, index=False, encoding="utf-8-sig")

    print("Writing data dictionary and validation report...")
    dictionary_sources = {
        "Prepared_Transactions": prepared, "Fact_Sales": fact, "Dim_Product": dim_product,
        "Dim_Date": dim_date, "Dim_Order": dim_order, "Dim_Shipping": dim_shipping, "Dim_Payment": dim_payment,
    }
    dictionary = {"Shopee_Source_Fields": shopee_source_dictionary(transactions)}
    dictionary.update({name: dictionary_sheet(frame) for name, frame in dictionary_sources.items()})
    write_excel(FINAL / "member1_data_dictionary.xlsx", dictionary)
    validation = make_validation(count_csv_rows(RAW_COMBINED), transactions, prepared, unmatched, base, product, final_master, (dim_product, dim_date, dim_order, dim_shipping, dim_payment), fact)
    write_excel(FINAL / "final_validation_report.xlsx", {
        "Validation_Overview": validation[0], "Category_Reconciliation": validation[1],
        "Dimension_Key_Checks": validation[2], "Orphan_Fact_Checks": validation[3],
        "Order_Conflicts": validation[4], "Data_Quality_Flags": validation[5],
        "Approved_Name_Examples": validation[6],
        "Unmatched_Products": unmatched.head(10_000),
    })

    failures = int(validation[0]["status"].eq("FAIL").sum())
    print("\nMember 1 final ETL handoff complete.")
    print(f"Prepared transactions: {len(prepared):,}")
    print(f"Product variations: {len(final_master):,}; base products: {len(base):,}; categories: {base.final_category.nunique():,}")
    print(f"Unique orders: {prepared['Order ID'].nunique():,}; order conflicts flagged: {len(validation[4]):,}")
    print(f"Validation failures: {failures:,}; unmatched product records: {len(unmatched):,}")
    print("Members 2–4: use prepared_transactions.csv for analysis-ready detail, fact_sales.csv plus dim_*.csv for the star schema, and product_master_final.xlsx for governed product labels.")
    print(f"Saved under: {FINAL}")


if __name__ == "__main__":
    main()
