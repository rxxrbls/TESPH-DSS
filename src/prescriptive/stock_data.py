"""Legacy loader for the dated sample stock snapshot; not the live app path.

The Streamlit workflow uses uploaded inventory validated in ``pages/data_upload.py``
and joined by ``prescriptive_pipeline.py``. Keep this adapter for compatibility
and sample-data tests only.
"""

from pathlib import Path
import pandas as pd
from src.prescriptive.recommendation_rules import classify_stock_out_risk


# KAN-258 - TA-APPROVED STOCK DATA SOURCE

APPROVED_STOCK_AS_OF_DATE = "2026-09-09"

APPROVED_STOCK_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "raw_data"
    / "current_stock"
    / "current_stock_inventory_2026-09-09.csv"
)


def load_current_stock():
    """
    Loads the approved current-stock snapshot for
    Stock-Out Risk calculations.
    """

    stock_df = pd.read_csv(APPROVED_STOCK_SOURCE)

    required_columns = {
        "product_key",
        "Current Stock",
        "Stock As-Of Date",
    }

    missing_columns = required_columns - set(stock_df.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required stock columns: {missing_columns}"
        )

    stock_df["Stock As-Of Date"] = pd.to_datetime(
        stock_df["Stock As-Of Date"]
    )

    approved_date = pd.Timestamp(APPROVED_STOCK_AS_OF_DATE)

    if not stock_df["Stock As-Of Date"].eq(approved_date).all():
        raise ValueError(
            "Stock data contains records outside the "
            "approved stock as-of date."
        )

    return stock_df[
        [
            "product_key",
            "Current Stock",
            "Stock As-Of Date",
        ]
    ].copy()

def calculate_stock_risk_from_approved_source(
    product_key,
    average_daily_forecast_demand,
    supplier_lead_time,
):
    """
    Uses Current Stock from the approved stock snapshot
    as input to the Stock-Out Risk calculation.
    """

    stock_df = load_current_stock()

    product_stock = stock_df[
        stock_df["product_key"] == product_key
    ]

    if product_stock.empty:
        raise ValueError(
            f"No approved stock record found for: {product_key}"
        )

    current_stock = product_stock.iloc[0]["Current Stock"]

    risk = classify_stock_out_risk(
        current_stock=current_stock,
        average_daily_forecast_demand=average_daily_forecast_demand,
        supplier_lead_time=supplier_lead_time,
    )

    return {
        "product_key": product_key,
        "current_stock": current_stock,
        "stock_as_of_date": product_stock.iloc[0]["Stock As-Of Date"],
        "risk": risk,
    }