"""Member 1 input/layout configuration and frozen historical field contracts.

No predictive/prescriptive methodology or inferred stock date belongs here.
"""
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FINAL_OUTPUT_DIR = ROOT / "final_outputs"
# ``final_outputs`` is the immutable governed Member 1 handoff.  Runtime
# uploads must never write there; the local application publishes its active
# reconciled snapshot separately.
RUNTIME_DATA_DIR = ROOT / "runtime_data"
RUNTIME_DB_PATH = RUNTIME_DATA_DIR / "active_transactions.db"
CURRENT_INVENTORY_SOURCE = (
    ROOT / "raw_data" / "current_stock" / "shopee_current_stock_raw_2026-09-09.xlsx"
)
INVENTORY_COLUMNS = (
    "Product ID", "Product Name", "Variation ID", "Variation Name",
    "Parent SKU", "SKU", "Price", "Stock",
)


@dataclass(frozen=True)
class InventoryConfig:
    source_path: Path = CURRENT_INVENTORY_SOURCE
    sheet_name: str = "Sheet1"
    header_row: int = 3  # One-based Excel row numbers.
    data_start_row: int = 7
    expected_columns: tuple[str, ...] = INVENTORY_COLUMNS
    stock_as_of: date | datetime | None = None  # Client supplied; never inferred.

    def __post_init__(self):
        object.__setattr__(self, "source_path", Path(self.source_path))
        if self.header_row < 1 or self.data_start_row <= self.header_row:
            raise ValueError("Inventory data_start_row must follow the header_row")
        if self.stock_as_of is not None and not isinstance(self.stock_as_of, date):
            raise ValueError("stock_as_of must be a client-supplied date/datetime or None")


# Exact baseline spellings. These are schema contracts, not column rename rules.
SOURCE_COLUMNS = (
    "Order ID", "Order Status", "Hot Listing", "Cancel reason", "Return / Refund Status",
    "Tracking Number*", "Shipping Option", "Shipment Method", "Estimated Ship Out Date",
    "Ship Time", "Order Creation Date", "Order Paid Time", "Parent SKU Reference No.",
    "Product Name", "SKU Reference No.", "Variation Name", "Original Price", "Deal Price",
    "Quantity", "Returned quantity", "Total Buyer Payment", "Total Discount(PHP)",
    "Price Discount(from Seller)(PHP)", "Shopee Rebate(PHP)", "SKU Total Weight",
    "Number of Items in Order", "Order Total Weight", "Seller Voucher(PHP)",
    "Coin Cashback Voucher Amount Sponsored by Seller", "Shopee Voucher(PHP)",
    "Bundle Deals Indicator(Y/N)", "Shopee Bundle Discount(PHP)", "Seller Bundle Discount(PHP)",
    "Shopee Coins Offset(PHP)", "Credit Card Discount Total(PHP)",
    "Products' Price Paid by Buyer (PHP)", "Buyer Paid Shipping Fee",
    "Shipping Rebate Estimate", "Reverse Shipping Fee", "Service Fee", "Grand Total",
    "Estimated Shipping Fee", "Username (Buyer)", "Receiver Name", "Phone Number",
    "Delivery Address", "Town", "District", "City", "Province", "Country", "Zip Code",
    "Remark from buyer", "Order Complete Time", "Note", "Invoice request type",
    "Invoice type", "Name", "Business number", "Address",
)
# The Shopee order-export contract is explicit.  Do not infer types from
# words in a heading (for example, ``Shipping Option`` is a carrier/service
# label, not a financial value).  These groups also make CSV and XLSX follow
# the same validation rules regardless of pandas' inferred dtypes.
DATE_SOURCE_COLUMNS = (
    "Estimated Ship Out Date", "Ship Time", "Order Creation Date",
    "Order Paid Time", "Order Complete Time",
)
MEASURE_COLUMNS = (
    "Quantity", "Returned quantity", "Original Price", "Deal Price", "Total Buyer Payment",
    "Total Discount(PHP)", "Price Discount(from Seller)(PHP)", "Shopee Rebate(PHP)",
    "SKU Total Weight", "Number of Items in Order", "Order Total Weight", "Seller Voucher(PHP)",
    "Coin Cashback Voucher Amount Sponsored by Seller", "Shopee Voucher(PHP)",
    "Shopee Bundle Discount(PHP)", "Seller Bundle Discount(PHP)", "Shopee Coins Offset(PHP)",
    "Credit Card Discount Total(PHP)", "Products' Price Paid by Buyer (PHP)",
    "Buyer Paid Shipping Fee", "Shipping Rebate Estimate", "Reverse Shipping Fee",
    "Service Fee", "Grand Total", "Estimated Shipping Fee",
)
TEXT_SOURCE_COLUMNS = tuple(
    column for column in SOURCE_COLUMNS
    if column not in set(DATE_SOURCE_COLUMNS) | set(MEASURE_COLUMNS)
)
SOURCE_COLUMN_TYPES = {
    **{column: "text" for column in TEXT_SOURCE_COLUMNS},
    **{column: "datetime" for column in DATE_SOURCE_COLUMNS},
    **{column: "numeric" for column in MEASURE_COLUMNS},
}
STATUS_COLUMNS = ("is_completed", "is_cancelled", "is_returned")
QUALITY_COLUMNS = ("has_negative_financial_value", "negative_financial_fields")
PROVENANCE_COLUMNS = ("source_file", "source_folder")
FINAL_SCHEMAS = {
    "prepared_transactions": SOURCE_COLUMNS + PROVENANCE_COLUMNS + (
        "standardized_product_name", "standardized_variation_name", "product_key",
    ) + QUALITY_COLUMNS + (
        "order_date", "order_year", "order_month", "year_month",
    ) + STATUS_COLUMNS + ("final_base_product_name", "final_category"),
    "fact_sales": (
        "sales_line_key", "Order ID", "product_key", "date_key", "shipping_key", "payment_key",
    ) + MEASURE_COLUMNS + QUALITY_COLUMNS + STATUS_COLUMNS + PROVENANCE_COLUMNS,
    "dim_product": (
        "product_key", "original Product Name", "original Variation Name", "final_base_product_name",
        "standardized Product Name", "standardized Variation Name", "Parent SKU", "SKU", "final_category",
    ),
    "dim_date": (
        "date_key", "full_date", "year", "quarter", "month_number", "month_name", "year_month",
        "day", "day_of_week",
    ),
    "dim_order": (
        "Order ID", "Order Status", "Cancel reason", "Return / Refund Status",
        "Estimated Ship Out Date", "Ship Time", "Order Creation Date", "Order Paid Time",
        "Order Complete Time", "Username (Buyer)", "Remark from buyer", "Note",
        "Number of Items in Order", "Order Total Weight", "Business number", "Name", "Address",
        "has_order_attribute_conflict", "conflicting_order_attributes",
    ),
    "dim_shipping": (
        "shipping_key", "Tracking Number*", "Shipping Option", "Shipment Method", "Receiver Name",
        "Phone Number", "Delivery Address", "Town", "District", "City", "Province", "Country", "Zip Code",
    ),
    "dim_payment": (
        "payment_key", "Hot Listing", "Bundle Deals Indicator(Y/N)", "Invoice request type", "Invoice type",
    ),
}
TEXT_IDENTIFIER_COLUMNS = (
    "Order ID", "product_key", "sales_line_key", "shipping_key", "payment_key",
    "Parent SKU Reference No.", "SKU Reference No.", "Parent SKU", "SKU",
    "Tracking Number*", "Phone Number", "Zip Code", "Business number",
)
