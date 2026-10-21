"""Approved MCA formulas with explicit periods and supplied source measures.

Net sales, net sold units and date-effective unit cost must come from a reconciled
source ledger. This module does not infer costs or refund settlements from revenue.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics_calculations import _require_columns


def measurement_period(start, end) -> tuple[pd.Timestamp, pd.Timestamp]:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError("MCA measurement period requires valid start and end dates in order")
    return start.normalize(), end.normalize()


def _period_rows(data, start, end, identifier="SKU", date="Date"):
    start, end = measurement_period(start, end)
    _require_columns(data, [identifier, date])
    result = data.copy()
    if result[identifier].isna().any() or result[identifier].astype(str).str.strip().eq("").any():
        raise ValueError("MCA source identifiers must not be missing")
    result[date] = pd.to_datetime(result[date], errors="coerce").dt.normalize()
    if result[date].isna().any():
        raise ValueError("MCA source dates must be valid")
    return result.loc[result[date].between(start, end)].copy()


def calculate_profit_margin(financial_lines: pd.DataFrame, *, period_start, period_end) -> pd.DataFrame:
    """100 * (sum(net sales) - sum(net sold units * applicable cost)) / net sales.

    Signed net units/sales accommodate reconciled returns. Missing/invalid costs
    invalidate the whole SKU period, never just drop an unfavorable source row.
    Unit Cost must already be the source-approved cost applicable to that line.
    """
    columns = ["Net Product Sales", "Net Units Sold", "Unit Cost"]
    _require_columns(financial_lines, ["SKU", "Date", *columns])
    data = _period_rows(financial_lines, period_start, period_end)
    rows = []
    for sku, group in data.groupby("SKU", sort=True):
        values = group[columns].apply(pd.to_numeric, errors="coerce")
        valid = np.isfinite(values.to_numpy(dtype=float)).all() and values["Unit Cost"].ge(0).all()
        sales = float(values["Net Product Sales"].sum()) if valid else np.nan
        cogs = float((values["Net Units Sold"] * values["Unit Cost"]).sum()) if valid else np.nan
        usable = valid and np.isfinite(sales) and np.isfinite(cogs) and sales > 0 and cogs >= 0
        rows.append({"SKU": sku, "Net Product Sales": sales, "COGS": cogs,
                     "Profit Margin": 100 * (sales - cogs) / sales if usable else np.nan,
                     "Profit Margin Status": "Available" if usable else "Unavailable: missing/invalid costs or nonpositive net sales/net COGS"})
    return pd.DataFrame(rows, columns=["SKU", "Net Product Sales", "COGS", "Profit Margin", "Profit Margin Status"])


def calculate_stock_out_frequency(stock_history: pd.DataFrame, *, period_start, period_end,
                                  identifier="SKU", date="Date", stock="Net Sellable Stock") -> pd.DataFrame:
    """Percentage of valid observed days with net sellable stock <= 0.

    A single snapshot cannot establish historical frequency. Missing days are
    not fabricated; invalid stocks are excluded and counted in the audit.
    Duplicate SKU-days require reconciliation, not arbitrary selection.
    """
    _require_columns(stock_history, [identifier, date, stock])
    data = _period_rows(stock_history, period_start, period_end, identifier, date)
    if data.duplicated([identifier, date]).any():
        raise ValueError("Stock history requires one reconciled observation per SKU-day")
    rows = []
    for sku, group in data.groupby(identifier, sort=True):
        values = pd.to_numeric(group[stock], errors="coerce")
        valid = np.isfinite(values.to_numpy(dtype=float))
        count = int(valid.sum())
        empty_days = int(values.loc[valid].le(0).sum())
        rows.append({identifier: sku, "Stock-Out Frequency": 100 * empty_days / count if count >= 2 else np.nan,
                     "Valid Observed Days": count, "Stock-Out Days": empty_days,
                     "Invalid Stock Days": int((~valid).sum()),
                     "Stock-Out Frequency Status": "Available" if count >= 2 else "Unavailable: fewer than two valid observed days"})
    return pd.DataFrame(rows, columns=[identifier, "Stock-Out Frequency", "Valid Observed Days", "Stock-Out Days", "Invalid Stock Days", "Stock-Out Frequency Status"])


def calculate_return_rate(returned: pd.Series, gross: pd.Series) -> pd.Series:
    """Unit-based percentage; no orders denominator and no zero imputation."""
    returned = pd.to_numeric(returned, errors="coerce")
    gross = pd.to_numeric(gross, errors="coerce")
    valid = np.isfinite(returned) & np.isfinite(gross) & gross.gt(0) & returned.ge(0) & returned.le(gross)
    return (100 * returned / gross.where(valid)).where(valid)
