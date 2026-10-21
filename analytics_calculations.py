"""Reusable descriptive analytics calculations for the Shopee handoff data.

This module deliberately contains no Streamlit code. Public calculation
functions accept a transaction DataFrame and return clean DataFrames that a UI
or export layer can consume later.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from methodology_config import GROSS_REVENUE_COLUMN, LOW_SALES_PERCENTILE


REQUIRED_SOURCE_COLUMNS = (
    "Order ID",
    "Order Status",
    "SKU Reference No.",
    "Product Name",
    "product_key",
    "final_base_product_name",
    "final_category",
    "order_date",
    "Quantity",
    "Returned quantity",
    "Deal Price",
    "Total Buyer Payment",
    "is_completed",
    "is_cancelled",
    "is_returned",
)

PRODUCT_COLUMNS = ["SKU", "Product", "Category"]
GROSS_REVENUE_SOURCE_COLUMN = GROSS_REVENUE_COLUMN
SERVICE_FEE_SOURCE_COLUMN = "Service Fee"
MOVEMENT_CLASSIFICATIONS = ("Fast Moving", "Regular Moving", "Slow Moving", "No Movement")
REVIEW_REQUIRED = "For Business-Owner Review"
NO_REVIEW_FLAG = "No Review Flag"


def _require_columns(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError("Required columns are missing: " + ", ".join(missing))


def _clean_text(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned.eq(""), pd.NA)


def _clean_boolean(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    values = _clean_text(series).str.casefold()
    known = {"true", "1", "yes", "y", "false", "0", "no", "n"}
    if (values.notna() & ~values.isin(known)).any():
        raise ValueError("Transaction flags must contain recognized boolean values")
    return values.isin({"true", "1", "yes", "y"}).fillna(False)


def _joined_unique_by_group(
    frame: pd.DataFrame, group_columns: list[str], value_column: str
) -> pd.DataFrame:
    """Join sorted unique labels per group after cleaning the column once."""
    values = _clean_text(frame[value_column])
    pairs = frame[group_columns].copy()
    pairs[value_column] = values
    pairs = pairs.dropna(subset=[value_column])
    if pairs.empty:
        return pd.DataFrame(columns=[*group_columns, value_column])

    pairs = pairs.sort_values(
        [*group_columns, value_column], kind="stable", na_position="last"
    ).drop_duplicates([*group_columns, value_column], keep="first")
    result = (
        pairs.groupby(group_columns, dropna=False, sort=True, observed=False)[value_column]
        .agg(" | ".join)
        .rename(value_column)
        .reset_index()
    )
    result[value_column] = result[value_column].astype("string")
    return result


def _safe_rate(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator_values = pd.to_numeric(numerator, errors="coerce").to_numpy(dtype=float)
    denominator_values = pd.to_numeric(denominator, errors="coerce").to_numpy(dtype=float)
    result = np.full(len(numerator_values), np.nan, dtype=float)
    np.divide(
        numerator_values,
        denominator_values,
        out=result,
        where=denominator_values != 0,
    )
    return pd.Series(result, index=numerator.index, dtype="float64")


def _normalise_frequency(frequency: str) -> str:
    normalised = str(frequency).strip().upper()
    aliases = {"MONTH": "M", "MONTHLY": "M", "WEEK": "W", "WEEKLY": "W"}
    normalised = aliases.get(normalised, normalised)
    if normalised not in {"D", "W", "M", "Q", "Y"}:
        raise ValueError("frequency must be one of: D, W, M, Q, Y")
    return normalised


def exclude_incomplete_latest_month(
    transactions: pd.DataFrame,
    *,
    date_column: str | None = None,
    coverage_end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Drop rows from the latest calendar month when that month is incomplete."""

    if transactions.empty:
        return transactions.copy()

    if date_column is not None:
        if date_column not in transactions.columns:
            raise ValueError(f"Date column is missing: {date_column}")
        candidate_columns = [date_column]
    else:
        candidate_columns = [
            column
            for column in ("order_date", "Time", "Order Creation Date")
            if column in transactions.columns
        ]
        if not candidate_columns:
            raise ValueError(
                "A date column is required to exclude an incomplete latest month"
            )

    selected_column = candidate_columns[0]
    times = pd.to_datetime(transactions[selected_column], errors="coerce")
    latest = pd.Timestamp(coverage_end) if coverage_end is not None else times.max()
    if pd.isna(latest):
        return transactions.copy()

    latest_date = latest.normalize()
    latest_month_end = (latest + pd.offsets.MonthEnd(0)).normalize()
    covered = times.dt.normalize().le(latest_date)
    if latest_date >= latest_month_end:
        return transactions.loc[covered].reset_index(drop=True)

    latest_period = latest.to_period("M")
    return transactions.loc[covered & times.dt.to_period("M").lt(latest_period)].reset_index(
        drop=True
    )


def _demand_values(frame: pd.DataFrame, demand_definition: str = "gross_demand") -> pd.Series:
    definitions = {
        "gross_demand": frame["Gross Demand"],
        "net_inventory_demand": frame["Net Inventory Demand"],
    }
    if demand_definition not in definitions:
        raise ValueError(
            "demand_definition must be gross_demand or net_inventory_demand"
        )
    return definitions[demand_definition].astype(float)


def assemble_star_schema_transactions(
    fact_sales: pd.DataFrame,
    dim_order: pd.DataFrame,
    dim_product: pd.DataFrame,
    dim_date: pd.DataFrame,
) -> pd.DataFrame:
    """Join the ETL star schema into the source contract used by analytics.

    The many-to-one validations prevent duplicate dimension rows from silently
    multiplying sales values. Order status comes from ``dim_order`` as required
    by the approved methodology.
    """

    _require_columns(
        fact_sales,
        [
            "Order ID",
            "product_key",
            "date_key",
            "Quantity",
            "Returned quantity",
            "Deal Price",
            GROSS_REVENUE_SOURCE_COLUMN,
            "is_completed",
            "is_cancelled",
            "is_returned",
        ],
    )
    _require_columns(dim_order, ["Order ID", "Order Status"])
    _require_columns(
        dim_product,
        [
            "product_key",
            "original Product Name",
            "SKU",
            "final_base_product_name",
            "final_category",
        ],
    )
    _require_columns(dim_date, ["date_key", "full_date"])

    if dim_order["Order ID"].duplicated().any():
        raise ValueError("dim_order must contain one row per Order ID")
    if dim_product["product_key"].duplicated().any():
        raise ValueError("dim_product must contain one row per product_key")
    if dim_date["date_key"].duplicated().any():
        raise ValueError("dim_date must contain one row per date_key")

    order_fields = ["Order ID", "Order Status"]
    for optional in ("Return / Refund Status", "Cancel reason"):
        if optional in dim_order.columns:
            order_fields.append(optional)
    product_fields = [
        "product_key",
        "original Product Name",
        "SKU",
        "final_base_product_name",
        "final_category",
    ]
    result = fact_sales.merge(
        dim_order[order_fields], on="Order ID", how="left", validate="many_to_one"
    )
    result = result.merge(
        dim_product[product_fields], on="product_key", how="left", validate="many_to_one"
    )
    result = result.merge(
        dim_date[["date_key", "full_date"]],
        on="date_key",
        how="left",
        validate="many_to_one",
    )
    required_joined = ["Order Status", "final_base_product_name", "final_category", "full_date"]
    if result[required_joined].isna().any().any():
        raise ValueError("Star-schema join produced missing required dimension values")
    return result.rename(
        columns={
            "original Product Name": "Product Name",
            "SKU": "SKU Reference No.",
            "full_date": "order_date",
        }
    )


def prepare_transactions(transactions: pd.DataFrame) -> pd.DataFrame:
    """Return the Member 1 handoff in a compact, analysis-friendly schema.

    Missing source SKU values remain missing. They are never replaced with a
    product key or another fabricated identifier.
    """

    _require_columns(transactions, REQUIRED_SOURCE_COLUMNS)
    prepared = pd.DataFrame(index=transactions.index)
    prepared["Order ID"] = _clean_text(transactions["Order ID"])
    prepared["Order Status"] = _clean_text(transactions["Order Status"])
    prepared["SKU"] = _clean_text(transactions["SKU Reference No."])
    prepared["Source Product Name"] = _clean_text(transactions["Product Name"])
    prepared["Product Key"] = _clean_text(transactions["product_key"])
    prepared["Product"] = _clean_text(transactions["final_base_product_name"])
    prepared["Category"] = _clean_text(transactions["final_category"])
    prepared["Time"] = pd.to_datetime(transactions["order_date"], errors="coerce")
    if prepared[["Order ID", "Product Key", "Product", "Category", "Time"]].isna().any().any():
        raise ValueError("Transactions require valid dates, order IDs, product keys, products, and categories")
    prepared["Quantity"] = pd.to_numeric(transactions["Quantity"], errors="coerce")
    prepared["Gross Revenue Source"] = pd.to_numeric(
        transactions[GROSS_REVENUE_SOURCE_COLUMN], errors="coerce"
    )
    if not np.isfinite(prepared[["Quantity", "Gross Revenue Source"]].to_numpy(dtype=float)).all():
        raise ValueError("Quantity and Total Buyer Payment must contain valid numeric values")
    if prepared["Quantity"].lt(0).any():
        raise ValueError("Quantity cannot be negative")
    prepared["Returned Quantity"] = pd.to_numeric(
        transactions["Returned quantity"], errors="coerce"
    ).fillna(0.0)
    prepared["Unit Price"] = pd.to_numeric(
        transactions["Deal Price"], errors="coerce"
    ).fillna(0.0)
    for source, target in (("Returned quantity", "Returned Quantity"), ("Deal Price", "Unit Price")):
        supplied = _clean_text(transactions[source]).notna()
        parsed = pd.to_numeric(transactions[source], errors="coerce")
        if (supplied & ~np.isfinite(parsed.to_numpy(dtype=float))).any() or prepared[target].lt(0).any():
            raise ValueError(f"{source} must be finite and nonnegative when supplied")
    if SERVICE_FEE_SOURCE_COLUMN in transactions.columns:
        prepared["Service Fee"] = pd.to_numeric(
            transactions[SERVICE_FEE_SOURCE_COLUMN], errors="coerce"
        )
        if not np.isfinite(prepared["Service Fee"].to_numpy(dtype=float)).all():
            raise ValueError("Service Fee must be numeric when supplied")
    else:
        prepared["Service Fee"] = np.nan
    prepared["Is Completed"] = _clean_boolean(transactions["is_completed"])
    prepared["Is Cancelled"] = _clean_boolean(transactions["is_cancelled"])
    prepared["Is Returned"] = _clean_boolean(transactions["is_returned"])
    prepared["Is Demand Order"] = prepared["Is Completed"] | prepared["Is Returned"]
    prepared["Has Returned Quantity"] = prepared["Returned Quantity"].gt(0) & prepared["Is Demand Order"]
    prepared["Gross Demand"] = prepared["Quantity"].where(
        prepared["Is Demand Order"], 0.0
    )
    prepared["Demand Returned Quantity"] = prepared["Returned Quantity"].where(
        prepared["Is Demand Order"], 0.0
    )
    prepared["Net Inventory Demand"] = (
        prepared["Gross Demand"] - prepared["Demand Returned Quantity"]
    ).clip(lower=0.0)
    prepared["Completed Quantity"] = prepared["Quantity"].where(
        prepared["Is Completed"], 0.0
    )
    prepared["Cancelled Quantity"] = prepared["Quantity"].where(
        prepared["Is Cancelled"], 0.0
    )
    prepared["Gross Revenue"] = prepared["Gross Revenue Source"].where(
        prepared["Is Completed"], 0.0
    )
    quantity_ratio = _safe_rate(prepared["Net Inventory Demand"], prepared["Gross Demand"])
    quantity_ratio = quantity_ratio.fillna(0.0).clip(lower=0.0, upper=1.0)
    prepared["Net Revenue After Returns"] = prepared["Gross Revenue"] * quantity_ratio
    return prepared.reset_index(drop=True)


def calculate_sales_summary(transactions: pd.DataFrame) -> pd.DataFrame:
    """KAN-31: calculate an overall sales summary as a one-row DataFrame."""

    frame = prepare_transactions(transactions)
    order_ids = frame["Order ID"]
    completed_orders = frame.loc[frame["Is Completed"], "Order ID"]
    demand_orders = frame.loc[frame["Is Demand Order"], "Order ID"]
    cancelled_orders = frame.loc[frame["Is Cancelled"], "Order ID"]
    returned_orders = frame.loc[frame["Is Returned"], "Order ID"]
    demand_line_count = int(frame["Is Demand Order"].sum())
    result = pd.DataFrame(
        [
            {
                "First Transaction Time": frame["Time"].min(),
                "Last Transaction Time": frame["Time"].max(),
                "Order Count": order_ids.nunique(dropna=True),
                "Line Count": len(frame),
                "Product Count": frame["Product Key"].nunique(dropna=True),
                "Category Count": frame["Category"].nunique(dropna=True),
                "All Ordered Quantity": frame["Quantity"].sum(),
                "Gross Demand": frame["Gross Demand"].sum(),
                "Net Inventory Demand": frame["Net Inventory Demand"].sum(),
                "Completed Quantity": frame["Completed Quantity"].sum(),
                "Cancelled Quantity": frame["Cancelled Quantity"].sum(),
                "Returned Quantity": frame["Demand Returned Quantity"].sum(),
                "Gross Revenue": frame["Gross Revenue"].sum(),
                "Net Revenue After Returns": frame["Net Revenue After Returns"].sum(),
                "Completed Order Count": completed_orders.nunique(dropna=True),
                "Demand Order Count": demand_orders.nunique(dropna=True),
                "Cancelled Order Count": cancelled_orders.nunique(dropna=True),
                "Return Order Count": returned_orders.nunique(dropna=True),
                "Return-Flagged Line Count": int(frame["Is Returned"].sum()),
                "Returned-Quantity Line Count": int(frame["Has Returned Quantity"].sum()),
                "Demand Line Count": demand_line_count,
            }
        ]
    )
    result["Average Order Value"] = _safe_rate(
        result["Gross Revenue"], result["Completed Order Count"]
    )
    result["Return Quantity Rate"] = _safe_rate(
        result["Returned Quantity"], result["Gross Demand"]
    )
    result["Return Order Rate"] = _safe_rate(
        result["Return Order Count"], result["Demand Order Count"]
    )
    result["Cancellation Order Rate"] = _safe_rate(
        result["Cancelled Order Count"], result["Order Count"]
    )
    return result


def calculate_product_performance(transactions: pd.DataFrame) -> pd.DataFrame:
    """KAN-32: calculate product performance while retaining SKU/Product/Category."""

    frame = prepare_transactions(transactions)
    frame["Return Order ID"] = frame["Order ID"].where(frame["Is Returned"])
    frame["Demand Order ID"] = frame["Order ID"].where(frame["Is Demand Order"])
    frame["Completed Order ID"] = frame["Order ID"].where(frame["Is Completed"])
    frame["Cancelled Line"] = frame["Is Cancelled"].astype(int)
    frame["Returned-Quantity Line"] = frame["Has Returned Quantity"].astype(int)
    grouped = frame.groupby(
        ["Product Key", "Product", "Category"], dropna=False, sort=True, observed=False
    )
    result = grouped.agg(
        **{
            "All Order Count": ("Order ID", "nunique"),
            "Demand Order Count": ("Demand Order ID", "nunique"),
            "Completed Order Count": ("Completed Order ID", "nunique"),
            "Line Count": ("Order ID", "size"),
            "Demand Line Count": ("Is Demand Order", "sum"),
            "All Ordered Quantity": ("Quantity", "sum"),
            "Gross Demand": ("Gross Demand", "sum"),
            "Net Inventory Demand": ("Net Inventory Demand", "sum"),
            "Completed Quantity": ("Completed Quantity", "sum"),
            "Cancelled Quantity": ("Cancelled Quantity", "sum"),
            "Returned Quantity": ("Demand Returned Quantity", "sum"),
            "Gross Revenue": ("Gross Revenue", "sum"),
            "Net Revenue After Returns": ("Net Revenue After Returns", "sum"),
            "Returned-Quantity Line Count": ("Returned-Quantity Line", "sum"),
            "Return Order Count": ("Return Order ID", "nunique"),
            "Cancelled Line Count": ("Cancelled Line", "sum"),
            "First Transaction Time": ("Time", "min"),
            "Last Transaction Time": ("Time", "max"),
        }
    ).reset_index()
    sku_labels = _joined_unique_by_group(frame, ["Product Key"], "SKU")
    result = result.merge(sku_labels, on="Product Key", how="left", validate="many_to_one")
    result["SKU"] = result["SKU"].astype("string")
    result["Return Quantity Rate"] = _safe_rate(
        result["Returned Quantity"], result["Gross Demand"]
    )
    result["Returned-Quantity Line Rate"] = _safe_rate(
        result["Returned-Quantity Line Count"], result["Demand Line Count"]
    )
    result["Cancellation Line Rate"] = _safe_rate(
        result["Cancelled Line Count"], result["Line Count"]
    )
    result["Average Unit Revenue"] = _safe_rate(
        result["Gross Revenue"], result["Completed Quantity"]
    )
    ordered_columns = [*PRODUCT_COLUMNS, "Product Key"] + [
        column for column in result.columns if column not in {*PRODUCT_COLUMNS, "Product Key"}
    ]
    return result[ordered_columns].sort_values(
        ["Gross Revenue", "Net Inventory Demand"], ascending=False, kind="stable"
    ).reset_index(drop=True)


def calculate_return_indicators(
    transactions: pd.DataFrame,
    group_by: Iterable[str] | None = None,
) -> pd.DataFrame:
    """KAN-34: calculate return indicators overall or by canonical dimensions."""

    frame = prepare_transactions(transactions)
    group_columns = list(group_by or [])
    allowed = {"SKU", "Product", "Category", "Order Status"}
    invalid = [column for column in group_columns if column not in allowed]
    if invalid:
        raise ValueError("Unsupported return grouping: " + ", ".join(invalid))

    frame["Return Order ID"] = frame["Order ID"].where(frame["Is Returned"])
    frame["Demand Order ID"] = frame["Order ID"].where(frame["Is Demand Order"])
    frame["Demand Line"] = frame["Is Demand Order"].astype(int)
    frame["Return-Flagged Line"] = frame["Is Returned"].astype(int)
    frame["Returned-Quantity Line"] = frame["Has Returned Quantity"].astype(int)
    if group_columns:
        grouped = frame.groupby(group_columns, dropna=False, sort=True, observed=False)
        result = grouped.agg(
            **{
                "All Order Count": ("Order ID", "nunique"),
                "Demand Order Count": ("Demand Order ID", "nunique"),
                "Line Count": ("Order ID", "size"),
                "Demand Line Count": ("Demand Line", "sum"),
                "Gross Demand": ("Gross Demand", "sum"),
                "Returned Quantity": ("Demand Returned Quantity", "sum"),
                "Return-Flagged Line Count": ("Return-Flagged Line", "sum"),
                "Returned-Quantity Line Count": ("Returned-Quantity Line", "sum"),
                "Return Order Count": ("Return Order ID", "nunique"),
            }
        ).reset_index()
    else:
        result = pd.DataFrame(
            [
                {
                    "All Order Count": frame["Order ID"].nunique(dropna=True),
                    "Demand Order Count": frame["Demand Order ID"].nunique(dropna=True),
                    "Line Count": len(frame),
                    "Demand Line Count": int(frame["Demand Line"].sum()),
                    "Gross Demand": frame["Gross Demand"].sum(),
                    "Returned Quantity": frame["Demand Returned Quantity"].sum(),
                    "Return-Flagged Line Count": int(frame["Return-Flagged Line"].sum()),
                    "Returned-Quantity Line Count": int(
                        frame["Returned-Quantity Line"].sum()
                    ),
                    "Return Order Count": frame["Return Order ID"].nunique(dropna=True),
                }
            ]
        )
    result["Return Quantity Rate"] = _safe_rate(
        result["Returned Quantity"], result["Gross Demand"]
    )
    result["Returned-Quantity Line Rate"] = _safe_rate(
        result["Returned-Quantity Line Count"], result["Demand Line Count"]
    )
    result["Return Order Rate"] = _safe_rate(
        result["Return Order Count"], result["Demand Order Count"]
    )
    return result


def calculate_net_seller_payout(
    transactions: pd.DataFrame,
    *,
    transaction_fee_column: str,
    group_by: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Calculate the optional net payout only when its actual fee field is supplied."""

    if transaction_fee_column not in transactions.columns:
        raise ValueError(
            f"Transaction fee column is missing: {transaction_fee_column}. "
            "Do not estimate or fabricate transaction fees."
        )
    if SERVICE_FEE_SOURCE_COLUMN not in transactions.columns:
        raise ValueError("Service Fee is required to calculate net seller payout")
    frame = prepare_transactions(transactions)
    transaction_fee = pd.to_numeric(
        transactions[transaction_fee_column], errors="coerce"
    ).reset_index(drop=True)
    if not np.isfinite(transaction_fee.to_numpy(dtype=float)).all():
        raise ValueError("The supplied transaction fee column must be numeric")

    net_ratio = _safe_rate(frame["Net Inventory Demand"], frame["Gross Demand"])
    net_ratio = net_ratio.fillna(0.0).clip(lower=0.0, upper=1.0)
    completed_service_fee = frame["Service Fee"].where(frame["Is Completed"], 0.0)
    completed_transaction_fee = transaction_fee.where(frame["Is Completed"], 0.0)
    frame["Net Seller Payout"] = (
        frame["Gross Revenue"] - completed_service_fee - completed_transaction_fee
    ) * net_ratio

    group_columns = list(group_by or [])
    allowed = {"SKU", "Product", "Category", "Order Status"}
    invalid = [column for column in group_columns if column not in allowed]
    if invalid:
        raise ValueError("Unsupported payout grouping: " + ", ".join(invalid))
    if not group_columns:
        return pd.DataFrame([{"Net Seller Payout": frame["Net Seller Payout"].sum()}])
    return (
        frame.groupby(group_columns, dropna=False, sort=True, observed=False)["Net Seller Payout"]
        .sum()
        .reset_index()
    )


def calculate_order_status_indicators(transactions: pd.DataFrame) -> pd.DataFrame:
    """KAN-35: calculate order-status and cancellation measures without UI code."""

    frame = prepare_transactions(transactions)
    total_lines = len(frame)
    total_orders = frame["Order ID"].nunique(dropna=True)
    result = (
        frame.groupby("Order Status", dropna=False, sort=True, observed=False)
        .agg(
            **{
                "Line Count": ("Order ID", "size"),
                "Order Count": ("Order ID", "nunique"),
                "Quantity": ("Quantity", "sum"),
                "Gross Revenue": ("Gross Revenue", "sum"),
            }
        )
        .reset_index()
    )
    result["Line Share"] = result["Line Count"] / total_lines if total_lines else np.nan
    result["Order Share"] = result["Order Count"] / total_orders if total_orders else np.nan
    return result.sort_values("Line Count", ascending=False, kind="stable").reset_index(drop=True)


def calculate_cancellation_indicators(transactions: pd.DataFrame) -> pd.DataFrame:
    """Cancellation reasons with distinct orders and cancelled line quantities."""
    frame = prepare_transactions(transactions)
    reasons = transactions.get("Cancel reason", pd.Series(pd.NA, index=transactions.index))
    frame["Cancel Reason"] = _clean_text(reasons).reset_index(drop=True).fillna("Unspecified")
    cancelled = frame.loc[frame["Is Cancelled"]]
    result = cancelled.groupby("Cancel Reason", sort=True).agg(
        **{"Cancelled Order Count": ("Order ID", "nunique"),
           "Cancelled Line Count": ("Order ID", "size"),
           "Cancelled Quantity": ("Cancelled Quantity", "sum")}
    ).reset_index()
    count = frame["Order ID"].nunique()
    result["Share of All Orders"] = result["Cancelled Order Count"] / count if count else np.nan
    return result


def calculate_sales_trends(
    transactions: pd.DataFrame,
    *,
    frequency: str,
) -> pd.DataFrame:
    """Calculate category sales trends at an explicitly approved frequency."""

    frequency = _normalise_frequency(frequency)
    frame = prepare_transactions(transactions).dropna(subset=["Time", "Category"])
    frame["Time"] = frame["Time"].dt.to_period(frequency).dt.to_timestamp()
    return (
        frame.groupby(["Time", "Category"], dropna=False, sort=True, observed=False)
        .agg(
            **{
                "Order Count": ("Order ID", "nunique"),
                "Gross Demand": ("Gross Demand", "sum"),
                "Net Inventory Demand": ("Net Inventory Demand", "sum"),
                "Completed Quantity": ("Completed Quantity", "sum"),
                "Returned Quantity": ("Demand Returned Quantity", "sum"),
                "Gross Revenue": ("Gross Revenue", "sum"),
                "Net Revenue After Returns": ("Net Revenue After Returns", "sum"),
            }
        )
        .reset_index()
    )


def calculate_product_movement_metrics(
    transactions: pd.DataFrame,
    *,
    frequency: str,
    recent_periods: int,
    demand_definition: str = "gross_demand",
    as_of: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """KAN-36: calculate product movement inputs without inventing thresholds."""

    if not isinstance(recent_periods, int) or recent_periods < 1:
        raise ValueError("recent_periods must be a positive integer from the methodology")
    frequency = _normalise_frequency(frequency)
    frame = prepare_transactions(transactions).dropna(subset=["Time", "Product Key"])
    frame["Demand"] = _demand_values(frame, demand_definition)
    frame["Period"] = frame["Time"].dt.to_period(frequency)
    period_demand = (
        frame.groupby(
            ["Product Key", "Product", "Category", "Period"],
            dropna=False,
            sort=True,
            observed=False,
        )["Demand"]
        .sum()
        .reset_index()
    )
    if period_demand.empty:
        return pd.DataFrame(
            columns=[
                *PRODUCT_COLUMNS,
                "Product Key",
                "Recent Demand",
                "Previous Demand",
                "Recent Average Demand",
                "Recent Positive-Demand Periods",
                "Demand Change",
                "Demand Change Rate",
                "Last Sale Time",
                "Periods Since Last Sale",
            ]
        )

    latest_period = pd.Timestamp(as_of).to_period(frequency) if as_of is not None else period_demand["Period"].max()
    recent_start = latest_period - (recent_periods - 1)
    previous_start = recent_start - recent_periods
    period_demand["Is Recent"] = period_demand["Period"].between(recent_start, latest_period)
    period_demand["Is Previous"] = period_demand["Period"].between(
        previous_start, recent_start - 1
    )
    period_demand["Recent Demand Value"] = period_demand["Demand"].where(
        period_demand["Is Recent"], 0.0
    )
    period_demand["Previous Demand Value"] = period_demand["Demand"].where(
        period_demand["Is Previous"], 0.0
    )
    period_demand["Recent Positive Demand"] = (
        period_demand["Is Recent"] & period_demand["Demand"].gt(0)
    ).astype(int)
    positive_period = period_demand["Period"].where(period_demand["Demand"] > 0)
    period_demand["Positive Sale Period"] = positive_period

    result = (
        period_demand.groupby(
            ["Product Key", "Product", "Category"], dropna=False, sort=True, observed=False
        )
        .agg(
            **{
                "Recent Demand": ("Recent Demand Value", "sum"),
                "Previous Demand": ("Previous Demand Value", "sum"),
                "Recent Positive-Demand Periods": ("Recent Positive Demand", "sum"),
                "Last Sale Period": ("Positive Sale Period", "max"),
            }
        )
        .reset_index()
    )
    sku_by_product = _joined_unique_by_group(frame, ["Product Key"], "SKU")
    result = result.merge(sku_by_product, on="Product Key", how="left", validate="one_to_one")
    result["Recent Average Demand"] = result["Recent Demand"] / recent_periods
    result["Demand Change"] = result["Recent Demand"] - result["Previous Demand"]
    result["Demand Change Rate"] = _safe_rate(
        result["Demand Change"], result["Previous Demand"]
    )
    result["Last Sale Time"] = result["Last Sale Period"].dt.to_timestamp()
    period_ordinals = result["Last Sale Period"].map(
        lambda value: value.ordinal if pd.notna(value) else np.nan
    )
    result["Periods Since Last Sale"] = latest_period.ordinal - period_ordinals
    result["Periods Since Last Sale"] = result["Periods Since Last Sale"].fillna(
        len(pd.period_range(period_demand["Period"].min(), latest_period, freq=frequency))
    ).astype(int)
    result = result.drop(columns="Last Sale Period")
    ordered_columns = [*PRODUCT_COLUMNS, "Product Key"] + [
        column for column in result.columns if column not in {*PRODUCT_COLUMNS, "Product Key"}
    ]
    return result[ordered_columns]


def calculate_low_sales_threshold(
    movement_metrics: pd.DataFrame,
    *,
    percentile: float = LOW_SALES_PERCENTILE,
) -> pd.DataFrame:
    """Calculate the category low-sales threshold from positive recent demand."""

    _require_columns(movement_metrics, ["Category", "Recent Demand"])
    if not np.isfinite(float(percentile)) or not 0 <= float(percentile) <= 100:
        raise ValueError("percentile must be a finite value between 0 and 100")

    result = movement_metrics[["Category", "Recent Demand"]].copy()
    result["Recent Demand"] = pd.to_numeric(result["Recent Demand"], errors="coerce")
    positive = result.loc[result["Recent Demand"].gt(0)]
    if positive.empty:
        return pd.DataFrame(columns=["Category", "Low Sales Threshold"])

    return (
        positive.groupby("Category", dropna=False, sort=True, observed=False)[
            "Recent Demand"
        ]
        .quantile(float(percentile) / 100.0)
        .rename("Low Sales Threshold")
        .reset_index()
    )


def classify_product_movement(
    movement_metrics: pd.DataFrame,
    *,
    low_sales_max_recent_average: float | None = None,
    low_sales_max_recent_demand: float | None = None,
    regular_moving_min_positive_periods: int,
    fast_moving_min_positive_periods: int,
) -> pd.DataFrame:
    """Classify movement using explicit thresholds supplied by the methodology.

    ``low_sales_max_recent_average`` is accepted for older callers, but the
    threshold is applied to Recent Demand per the confirmed methodology.
    """

    _require_columns(
        movement_metrics,
        [
            *PRODUCT_COLUMNS,
            "Product Key",
            "Recent Demand",
            "Recent Average Demand",
            "Recent Positive-Demand Periods",
        ],
    )
    if low_sales_max_recent_demand is None:
        if low_sales_max_recent_average is None:
            raise ValueError("low_sales_max_recent_demand is required")
        low_sales_max_recent_demand = low_sales_max_recent_average
    elif (
        low_sales_max_recent_average is not None
        and not np.isclose(low_sales_max_recent_demand, low_sales_max_recent_average)
    ):
        raise ValueError("Provide only one low-sales threshold value")
    if low_sales_max_recent_demand < 0:
        raise ValueError("low_sales_max_recent_demand cannot be negative")
    if regular_moving_min_positive_periods < 1:
        raise ValueError("regular_moving_min_positive_periods must be positive")
    if fast_moving_min_positive_periods <= regular_moving_min_positive_periods:
        raise ValueError(
            "fast_moving_min_positive_periods must exceed the regular-moving minimum"
        )

    result = movement_metrics.copy()
    recent_demand = pd.to_numeric(result["Recent Demand"], errors="coerce")
    result["Low Sales Flag"] = recent_demand.gt(0) & recent_demand.le(
        low_sales_max_recent_demand
    )
    positive_periods = pd.to_numeric(
        result["Recent Positive-Demand Periods"], errors="coerce"
    )
    result["Movement Classification"] = np.select(
        [
            recent_demand.le(0),
            positive_periods.ge(fast_moving_min_positive_periods),
            positive_periods.ge(regular_moving_min_positive_periods),
        ],
        ["No Movement", "Fast Moving", "Regular Moving"],
        default="Slow Moving",
    )
    result["Slow Moving Flag"] = result["Movement Classification"].isin(
        {"Slow Moving", "No Movement"}
    )
    result["Review Status"] = np.where(
        result["Low Sales Flag"] | result["Slow Moving Flag"],
        REVIEW_REQUIRED,
        NO_REVIEW_FLAG,
    )
    return result


def identify_products_for_review(
    transactions: pd.DataFrame,
    *,
    frequency: str,
    recent_periods: int,
    demand_definition: str,
    low_sales_max_recent_average: float | None = None,
    low_sales_max_recent_demand: float | None = None,
    regular_moving_min_positive_periods: int,
    fast_moving_min_positive_periods: int,
) -> pd.DataFrame:
    """KAN-38: return low-sales/slow-moving products for owner review."""

    metrics = calculate_product_movement_metrics(
        transactions,
        frequency=frequency,
        recent_periods=recent_periods,
        demand_definition=demand_definition,
    )
    classified = classify_product_movement(
        metrics,
        low_sales_max_recent_average=low_sales_max_recent_average,
        low_sales_max_recent_demand=low_sales_max_recent_demand,
        regular_moving_min_positive_periods=regular_moving_min_positive_periods,
        fast_moving_min_positive_periods=fast_moving_min_positive_periods,
    )
    return classified.loc[classified["Review Status"].eq(REVIEW_REQUIRED)].reset_index(
        drop=True
    )


def calculate_sales_velocity(
    transactions: pd.DataFrame,
    *,
    frequency: str,
    recent_periods: int,
    demand_definition: str = "gross_demand",
    as_of: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Return product sales velocity for an explicitly selected recent window."""

    result = calculate_product_movement_metrics(
        transactions,
        frequency=frequency,
        recent_periods=recent_periods,
        demand_definition=demand_definition,
        as_of=as_of,
    )
    result = result.rename(columns={"Recent Average Demand": "Sales Velocity"})
    result["Velocity Period Count"] = recent_periods
    return result[[*PRODUCT_COLUMNS, "Product Key", "Sales Velocity", "Velocity Period Count"]]


def calculate_yoy_revenue_growth(
    transactions: pd.DataFrame,
    *,
    through_month: int,
) -> pd.DataFrame:
    """Compare completed gross revenue through the same month of each year."""

    if not isinstance(through_month, int) or isinstance(through_month, bool):
        raise ValueError("through_month must be an integer from 1 to 12")
    if not 1 <= through_month <= 12:
        raise ValueError("through_month must be an integer from 1 to 12")
    frame = prepare_transactions(transactions).dropna(subset=["Time"])
    frame = frame.loc[frame["Time"].dt.month.le(through_month)].copy()
    frame["Year"] = frame["Time"].dt.year
    result = (
        frame.groupby("Year", sort=True, observed=False)["Gross Revenue"]
        .sum()
        .rename("Comparable Revenue")
        .reset_index()
    )
    revenue_by_year = result.set_index("Year")["Comparable Revenue"]
    result["Previous-Year Comparable Revenue"] = (result["Year"] - 1).map(revenue_by_year)
    result["YoY Revenue Growth"] = _safe_rate(
        result["Comparable Revenue"] - result["Previous-Year Comparable Revenue"],
        result["Previous-Year Comparable Revenue"],
    )
    result["Through Month"] = through_month
    return result


def calculate_kpis(transactions: pd.DataFrame) -> pd.DataFrame:
    """KAN-37: return core KPI calculations in a UI-neutral long table."""

    summary = calculate_sales_summary(transactions).iloc[0]
    rows = [
        ("Order Count", summary["Order Count"], "count"),
        ("Gross Demand", summary["Gross Demand"], "quantity"),
        ("Net Inventory Demand", summary["Net Inventory Demand"], "quantity"),
        ("Gross Revenue", summary["Gross Revenue"], "currency"),
        ("Net Revenue After Returns", summary["Net Revenue After Returns"], "currency"),
        ("Average Order Value", summary["Average Order Value"], "currency"),
        ("Return Quantity Rate", summary["Return Quantity Rate"], "ratio"),
        ("Return Order Rate", summary["Return Order Rate"], "ratio"),
        ("Cancellation Order Rate", summary["Cancellation Order Rate"], "ratio"),
    ]
    return pd.DataFrame(rows, columns=["KPI", "Value", "Unit"])
