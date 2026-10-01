"""Join the shared analytics, SKU forecast, and current-stock outputs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from active_inventory import build_active_mapping
from analytics_calculations import prepare_transactions
from methodology_config import (
    FORECAST_HORIZON,
    MCA_CRITERIA,
    REPLENISHMENT_CONFIG,
    STOCK_RISK_THRESHOLDS,
)
from prescriptive_calculations import (
    calculate_mca_scores,
    calculate_replenishment_quantity,
    calculate_safety_stock,
    calculate_stock_out_risk,
    calculate_target_stock_level,
    classify_recommendation_priority,
    recommendation_action,
)


def build_sku_mapping_from_stock_upload(
    transactions: pd.DataFrame,
    inventory_crosswalk: pd.DataFrame,
    *,
    stock_as_of: str | pd.Timestamp,
    as_of: str | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the existing fresh, exact, unique catalog rule to an uploaded snapshot."""

    required = {"product_key", "SKU", "Stock"}
    missing = sorted(required - set(inventory_crosswalk.columns))
    if missing:
        raise ValueError("Current-stock crosswalk is missing: " + ", ".join(missing))
    source = inventory_crosswalk[["product_key", "SKU", "Stock"]].copy()
    if {
        "crosswalk_product_key",
        "match_status",
        "mapping_review_required",
    }.issubset(inventory_crosswalk.columns):
        review_required = (
            inventory_crosswalk["mapping_review_required"]
            .astype("boolean")
            .fillna(True)
        )
        approved_match = (
            inventory_crosswalk["match_status"].eq("candidate")
            & review_required.eq(False)
        )
        source["product_key"] = inventory_crosswalk[
            "crosswalk_product_key"
        ].where(approved_match)
    source["Current Stock"] = pd.to_numeric(source.pop("Stock"), errors="coerce")
    source["Stock As-Of Date"] = pd.Timestamp(stock_as_of)
    return build_active_mapping(
        transactions,
        inventory=source,
        as_of=as_of,
        max_age_days=REPLENISHMENT_CONFIG.max_stock_age_days,
    )


def _forecast_by_sku(forecast: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    if forecast.empty:
        raise ValueError("No eligible SKU forecast is available")
    required = {"SKU", "Product", "Category", "Time", "Forecast"}
    missing = sorted(required - set(forecast.columns))
    if missing:
        raise ValueError("SKU forecast is missing: " + ", ".join(missing))
    result = forecast.copy()
    result["Time"] = pd.to_datetime(result["Time"], errors="coerce")
    result["Forecast"] = pd.to_numeric(result["Forecast"], errors="coerce")
    if result[["SKU", "Product", "Category", "Time", "Forecast"]].isna().any().any():
        raise ValueError("SKU forecast contains missing identifiers, dates, or demand")
    values = result["Forecast"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("SKU forecast demand must be finite and non-negative")
    if result.duplicated(["SKU", "Time"]).any():
        raise ValueError("SKU forecast must contain one row per SKU and forecast date")

    for sku, group in result.groupby("SKU", sort=True):
        dates = pd.DatetimeIndex(group["Time"].sort_values())
        if len(dates) != horizon_days or not (dates[1:] - dates[:-1] == pd.Timedelta(days=1)).all():
            raise ValueError(
                f"SKU {sku} must have exactly {horizon_days} consecutive daily forecast periods"
            )
        if group["Product"].nunique() != 1 or group["Category"].nunique() != 1:
            raise ValueError(f"SKU {sku} has conflicting forecast product metadata")

    return (
        result.groupby("SKU", as_index=False, sort=True)
        .agg(
            Product=("Product", "first"),
            Category=("Category", "first"),
            Forecast=("Forecast", "sum"),
        )
    )


def _safe_inventory(
    inventory_crosswalk: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None,
) -> pd.DataFrame:
    required = {
        "product_key", "SKU", "Stock", "stock_as_of", "match_status",
        "mapping_review_required", "stock_valid",
    }
    missing = sorted(required - set(inventory_crosswalk.columns))
    if missing:
        raise ValueError("Current-stock crosswalk is missing: " + ", ".join(missing))
    stock = inventory_crosswalk.copy()
    stock["stock_as_of"] = pd.to_datetime(stock["stock_as_of"], errors="coerce")
    stock["Stock"] = pd.to_numeric(stock["Stock"], errors="coerce")
    stock["mapping_review_required"] = stock["mapping_review_required"].astype("boolean").fillna(True)
    stock["stock_valid"] = stock["stock_valid"].astype("boolean").fillna(False)
    if "crosswalk_product_key" in stock:
        approved_match = (
            stock["match_status"].eq("candidate")
            & stock["mapping_review_required"].eq(False)
        )
        stock["product_key"] = stock["crosswalk_product_key"].where(
            approved_match
        )
    eligible = (
        stock["match_status"].eq("candidate")
        & stock["mapping_review_required"].eq(False)
        & stock["stock_valid"].eq(True)
        & stock["product_key"].notna()
        & stock["SKU"].notna()
        & stock["stock_as_of"].notna()
        & np.isfinite(stock["Stock"].fillna(0).to_numpy(dtype=float))
        & stock["Stock"].ge(0)
    )
    today = pd.Timestamp(as_of).normalize() if as_of is not None else pd.Timestamp.today().normalize()
    age = (today - stock["stock_as_of"].dt.normalize()).dt.days
    eligible &= age.between(0, REPLENISHMENT_CONFIG.max_stock_age_days)
    safe = stock.loc[eligible, ["product_key", "SKU", "Stock"]].copy()
    if safe["product_key"].duplicated().any() or safe["SKU"].duplicated().any():
        raise ValueError("Current-stock matches must be unique by product key and SKU")
    safe["Stock"] = safe["Stock"].astype(float)
    return safe


def run_prescriptive_pipeline(
    transactions: pd.DataFrame,
    analytics_results: dict[str, pd.DataFrame],
    forecast_results: dict[str, pd.DataFrame],
    inventory_crosswalk: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    forecast_horizon_days: int = FORECAST_HORIZON,
) -> dict[str, pd.DataFrame]:
    """Produce one risk, MCA, and replenishment result from the current upload."""

    if not isinstance(forecast_horizon_days, int) or isinstance(forecast_horizon_days, bool) or forecast_horizon_days < 1:
        raise ValueError("forecast_horizon_days must be a positive integer")
    forecast = _forecast_by_sku(forecast_results.get("forecast_output", pd.DataFrame()), forecast_horizon_days)
    safe_stock = _safe_inventory(inventory_crosswalk, as_of=as_of)
    stock_for_risk = safe_stock.rename(columns={"Stock": "Current Stock"})
    risk = calculate_stock_out_risk(
        forecast[["SKU", "Forecast"]],
        stock_for_risk[["SKU", "Current Stock"]],
        item_columns=["SKU"],
        forecast_horizon_days=forecast_horizon_days,
        thresholds=STOCK_RISK_THRESHOLDS,
    )
    risk = forecast[["SKU", "Product", "Category"]].merge(
        risk, on="SKU", how="left", validate="one_to_one"
    )

    prepared = prepare_transactions(transactions)
    mapped = safe_stock[["product_key", "SKU"]]
    sales = analytics_results.get("sales_velocity", pd.DataFrame()).copy()
    performance = analytics_results.get("product_performance", pd.DataFrame()).copy()
    if not {"Product Key", "Sales Velocity"}.issubset(sales.columns):
        raise ValueError("Analytics output is missing product-level sales velocity")
    if not {"Product Key", "Gross Revenue", "Gross Demand", "Returned Quantity"}.issubset(performance.columns):
        raise ValueError("Analytics output is missing product-level revenue or return measures")

    sales = sales[["Product Key", "Sales Velocity"]].merge(
        mapped, left_on="Product Key", right_on="product_key", how="inner", validate="many_to_one"
    )
    sales_by_sku = sales.groupby("SKU", as_index=False, sort=True)["Sales Velocity"].sum(
        min_count=1
    )
    financial = performance[["Product Key", "Gross Revenue", "Gross Demand", "Returned Quantity"]].merge(
        mapped, left_on="Product Key", right_on="product_key", how="inner", validate="many_to_one"
    )
    financial_by_sku = financial.groupby("SKU", as_index=False, sort=True)[
        ["Gross Revenue", "Gross Demand", "Returned Quantity"]
    ].sum(min_count=1)
    financial_by_sku["Return Rate"] = np.divide(
        financial_by_sku["Returned Quantity"],
        financial_by_sku["Gross Demand"],
        out=np.full(len(financial_by_sku), np.nan, dtype=float),
        where=financial_by_sku["Gross Demand"].to_numpy(dtype=float) > 0,
    )

    criteria = (
        risk.merge(sales_by_sku, on="SKU", how="left", validate="one_to_one")
        .merge(financial_by_sku, on="SKU", how="left", validate="one_to_one")
        .rename(columns={"Risk Index": "Projected Stock-Out Risk", "Forecast Demand": "Forecasted Demand"})
    )
    criteria["Supplier Lead Time"] = REPLENISHMENT_CONFIG.supplier_lead_time_days
    criteria = criteria.dropna(subset=list(MCA_CRITERIA))
    mca = calculate_mca_scores(criteria[["SKU", *MCA_CRITERIA]], identifier_columns=["SKU"])

    recommendation = risk.loc[risk["Current Stock"].notna()].merge(
        mca, on="SKU", how="left", validate="one_to_one"
    )
    recommendation["Safety Stock"] = recommendation["Forecast Demand"].map(
        lambda demand: calculate_safety_stock(
            demand, forecast_horizon_days=forecast_horizon_days,
            safety_stock_days=REPLENISHMENT_CONFIG.safety_stock_days,
        )
    )
    recommendation["Target Stock Level"] = recommendation["Forecast Demand"].map(
        lambda demand: calculate_target_stock_level(
            demand,
            forecast_horizon_days=forecast_horizon_days,
            lead_time_days=REPLENISHMENT_CONFIG.supplier_lead_time_days,
            review_period_days=REPLENISHMENT_CONFIG.review_period_days,
            safety_stock_days=REPLENISHMENT_CONFIG.safety_stock_days,
        )
    )
    recommendation["Recommended Quantity"] = [
        calculate_replenishment_quantity(target, stock)
        for target, stock in zip(recommendation["Target Stock Level"], recommendation["Current Stock"])
    ]
    recommendation["Recommendation"] = [
        recommendation_action(quantity, risk_level)
        for quantity, risk_level in zip(
            recommendation["Recommended Quantity"], recommendation["Stock-Out Risk"]
        )
    ]
    recommendation["Recommendation Priority"] = [
        classify_recommendation_priority(quantity, risk_level, mca_level)
        for quantity, risk_level, mca_level in zip(
            recommendation["Recommended Quantity"], recommendation["Stock-Out Risk"],
            recommendation["Priority Level"],
        )
    ]
    if recommendation.empty:
        recommendation["Recommendation Explanation"] = pd.Series(dtype="string")
    else:
        recommendation["Recommendation Explanation"] = recommendation.apply(
            lambda row: (
            f"{row['Recommendation']}: {int(row['Recommended Quantity'])} units; "
            f"current stock {row['Current Stock']:g}, target {int(row['Target Stock Level'])} "
                f"({forecast_horizon_days}-day forecast rate extended across "
                f"{REPLENISHMENT_CONFIG.supplier_lead_time_days + REPLENISHMENT_CONFIG.review_period_days} "
                f"lead/review days, plus {REPLENISHMENT_CONFIG.safety_stock_days} "
                f"safety-stock day(s), or {int(row['Safety Stock'])} units). "
            f"Risk {row['Stock-Out Risk']} ("
            + (
                f"DOI {row['Days of Inventory']:.1f} days"
                if pd.notna(row["Days of Inventory"])
                else "DOI not applicable"
            )
            + f", Risk Index {row['Risk Index']:.3f}); "
            + (
                f"MCA {row['Priority Level']} rank {int(row['Priority Rank'])}, "
                f"score {row['SKU Priority Score']:.3f}."
                if pd.notna(row.get("Priority Level"))
                else "MCA unavailable because one or more criteria are unsupported for this SKU."
            )
            ),
            axis=1,
        )
    return {
        "risk_results": risk,
        "mca_results": mca,
        "recommendation_results": recommendation,
    }