"""Join the shared analytics, SKU forecast, and current-stock outputs."""

from __future__ import annotations

import ast
from dataclasses import fields
import logging

import numpy as np
import pandas as pd

from active_inventory import build_active_mapping
from analytics_calculations import prepare_transactions
from mca_inputs import calculate_profit_margin, calculate_return_rate, measurement_period
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
    max_stock_age_days: int = REPLENISHMENT_CONFIG.max_stock_age_days,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the existing fresh, exact, unique catalog rule to an uploaded snapshot."""

    required = {"product_key", "SKU", "Stock"}
    missing = sorted(required - set(inventory_crosswalk.columns))
    if missing:
        raise ValueError("Current-stock crosswalk is missing: " + ", ".join(missing))
    source_columns = ["product_key", "SKU", "Stock"]
    if "Supplier Lead Time" in inventory_crosswalk.columns:
        source_columns.append("Supplier Lead Time")
    if "Supplier Lead Time Source" in inventory_crosswalk.columns:
        source_columns.append("Supplier Lead Time Source")
    source = inventory_crosswalk[source_columns].copy()
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
        max_age_days=max_stock_age_days,
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
    max_stock_age_days: int,
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
    if "Supplier Lead Time" in stock.columns:
        original_lead_time = stock["Supplier Lead Time"]
        parsed_lead_time = pd.to_numeric(original_lead_time, errors="coerce")
        invalid_lead_time = original_lead_time.notna() & (
            parsed_lead_time.isna() | parsed_lead_time.le(0)
        )
        if invalid_lead_time.any():
            raise ValueError("Supplier Lead Time must be a positive number of days")
        stock["Supplier Lead Time"] = parsed_lead_time
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
    eligible &= age.between(0, max_stock_age_days)
    safe_columns = ["product_key", "SKU", "Stock"]
    if "Supplier Lead Time" in stock.columns:
        safe_columns.append("Supplier Lead Time")
    if "Supplier Lead Time Source" in stock.columns:
        safe_columns.append("Supplier Lead Time Source")
    safe = stock.loc[eligible, safe_columns].copy()
    if safe["product_key"].duplicated().any() or safe["SKU"].duplicated().any():
        raise ValueError("Current-stock matches must be unique by product key and SKU")
    safe["Stock"] = safe["Stock"].astype(float)
    return safe


def _recorded_forecast_config(forecast_results: dict, horizon_days: int):
    """Restore the recorded forecast settings for a date-aligned regeneration."""
    from methodology_config import ForecastConfig

    defaults = ForecastConfig()
    values = {item.name: getattr(defaults, item.name) for item in fields(ForecastConfig)}
    recorded = forecast_results.get("methodology")
    if isinstance(recorded, pd.DataFrame) and {"Parameter", "Value"}.issubset(recorded.columns):
        for row in recorded.itertuples(index=False):
            name = str(getattr(row, "Parameter"))
            if name not in values:
                continue
            try:
                values[name] = ast.literal_eval(str(getattr(row, "Value")))
            except (ValueError, SyntaxError):
                values[name] = str(getattr(row, "Value"))
    if "horizon" in values and values["horizon"] != horizon_days:
        raise ValueError(
            "The configured forecast horizon does not match the active prescriptive horizon; "
            "refresh forecasts with the approved horizon before MCA assessment."
        )
    config = ForecastConfig(**values)
    config.validate()
    return config


def _regenerate_aligned_forecast(
    transactions: pd.DataFrame,
    forecast_results: dict,
    assessment_end: pd.Timestamp,
    horizon_days: int,
) -> dict:
    """Regenerate only with the active SKU mapping and recorded method settings."""
    from sku_forecasting import run_sku_forecasting

    mapping = forecast_results.get("sku_mapping")
    if not isinstance(mapping, pd.DataFrame) or mapping.empty:
        raise ValueError(
            "The active forecast has no SKU mapping; refresh stock mapping before "
            "regenerating a date-aligned forecast."
        )
    config = _recorded_forecast_config(forecast_results, horizon_days)
    regenerated = run_sku_forecasting(
        transactions=transactions,
        mapping=mapping,
        coverage_end=assessment_end,
        config=config,
    )
    output = regenerated.get("forecast_output")
    if not isinstance(output, pd.DataFrame) or output.empty or "Time" not in output:
        raise ValueError("Forecast regeneration produced no eligible SKU forecasts.")
    actual_dates = pd.DatetimeIndex(pd.to_datetime(output["Time"], errors="coerce").dropna().dt.normalize().unique()).sort_values()
    expected_dates = pd.date_range(
        assessment_end + pd.Timedelta(days=1), periods=horizon_days, freq="D"
    )
    if not actual_dates.equals(expected_dates):
        raise ValueError(
            "Regenerated forecast dates do not exactly cover the configured daily horizon "
            "after the MCA assessment endpoint."
        )
    return regenerated


def run_prescriptive_pipeline(
    transactions: pd.DataFrame,
    analytics_results: dict[str, pd.DataFrame],
    forecast_results: dict[str, pd.DataFrame],
    inventory_crosswalk: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    forecast_horizon_days: int = FORECAST_HORIZON,
    max_stock_age_days: int = REPLENISHMENT_CONFIG.max_stock_age_days,
    mca_financial_lines: pd.DataFrame | None = None,
    mca_stock_history: pd.DataFrame | None = None,
    mca_period_start: str | pd.Timestamp | None = None,
    mca_period_end: str | pd.Timestamp | None = None,
    mca_use_lead_time_fallback: bool = False,
    mca_return_snapshot: pd.DataFrame | None = None,
    mca_coverage=None,
    mca_weight_scenario: str = "equal_thirds",
) -> dict[str, pd.DataFrame]:
    """Produce risk, five-criterion MCA, and replenishment outputs.

    mca_stock_history is retained for caller compatibility but is not used.
    Historical stock frequency is no longer an MCA criterion.
    """

    if mca_coverage is not None:
        mca_coverage.validate()
        for supplied, configured in ((mca_period_start, mca_coverage.order_start),
                                     (mca_period_end, mca_coverage.order_end)):
            if supplied is not None and pd.Timestamp(supplied).normalize() != pd.Timestamp(configured).normalize():
                raise ValueError("MCA measurement dates must match the return/refund coverage configuration")
        mca_period_start, mca_period_end = mca_coverage.order_start, mca_coverage.order_end
    if not isinstance(forecast_horizon_days, int) or isinstance(forecast_horizon_days, bool) or forecast_horizon_days < 1:
        raise ValueError("forecast_horizon_days must be a positive integer")
    if mca_coverage is not None:
        assessment_end = pd.Timestamp(mca_coverage.order_end).normalize()
        active_output = forecast_results.get("forecast_output", pd.DataFrame())
        active_dates = (
            pd.to_datetime(active_output["Time"], errors="coerce").dropna().dt.normalize()
            if isinstance(active_output, pd.DataFrame) and "Time" in active_output
            else pd.Series(dtype="datetime64[ns]")
        )
        expected_dates = pd.date_range(
            assessment_end + pd.Timedelta(days=1), periods=forecast_horizon_days, freq="D"
        )
        if not active_dates.empty and not pd.DatetimeIndex(active_dates.unique()).sort_values().equals(expected_dates):
            LOGGER = logging.getLogger(__name__)
            LOGGER.warning(
                "Forecast dates do not match the MCA assessment window; regenerating "
                "with the active mapping and recorded methodology."
            )
            forecast_results = _regenerate_aligned_forecast(
                transactions, forecast_results, assessment_end, forecast_horizon_days
            )
        elif active_dates.empty:
            raise ValueError("No forecast dates are available for the MCA assessment window.")
    forecast = _forecast_by_sku(forecast_results.get("forecast_output", pd.DataFrame()), forecast_horizon_days)
    if isinstance(max_stock_age_days, bool) or not isinstance(max_stock_age_days, int) or max_stock_age_days < 1:
        raise ValueError("max_stock_age_days must be a positive integer")
    safe_stock = _safe_inventory(
        inventory_crosswalk, as_of=as_of, max_stock_age_days=max_stock_age_days
    )
    stock_for_risk = safe_stock.rename(columns={"Stock": "Current Stock"})
    risk_inventory_columns = ["SKU", "Current Stock"]
    if "Supplier Lead Time" in stock_for_risk.columns:
        risk_inventory_columns.append("Supplier Lead Time")
    if "Supplier Lead Time Source" in stock_for_risk.columns:
        risk_inventory_columns.append("Supplier Lead Time Source")
    risk = calculate_stock_out_risk(
        forecast[["SKU", "Forecast"]],
        stock_for_risk[risk_inventory_columns],
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
    if not {"Product Key", "Sales Velocity"}.issubset(sales.columns):
        raise ValueError("Analytics output is missing product-level sales velocity")

    sales = sales[["Product Key", "Sales Velocity"]].merge(
        mapped, left_on="Product Key", right_on="product_key", how="inner", validate="many_to_one"
    )
    sales_by_sku = sales.groupby("SKU", as_index=False, sort=True)["Sales Velocity"].sum(
        min_count=1
    )
    financial_by_sku = forecast[["SKU"]].copy()
    financial_by_sku["Return Rate"] = np.nan
    has_period = mca_period_start is not None and mca_period_end is not None
    if (mca_period_start is None) != (mca_period_end is None):
        raise ValueError("Supply both MCA measurement period dates")
    if not isinstance(mca_use_lead_time_fallback, bool):
        raise ValueError("mca_use_lead_time_fallback must be an explicit boolean")
    if has_period:
        start, end = measurement_period(mca_period_start, mca_period_end)
        period_sales = prepared.loc[prepared["Time"].dt.normalize().between(start, end)].merge(
            mapped, left_on="Product Key", right_on="product_key", how="inner", suffixes=(" Source", ""), validate="many_to_one"
        )
        units = period_sales.groupby("SKU")[["Gross Demand", "Demand Returned Quantity"]].sum(min_count=1)
        rates = calculate_return_rate(units["Demand Returned Quantity"], units["Gross Demand"])
        financial_by_sku["Return Rate"] = financial_by_sku["SKU"].map(rates)

    criteria = (
        risk.merge(sales_by_sku, on="SKU", how="left", validate="one_to_one")
        .merge(financial_by_sku, on="SKU", how="left", validate="one_to_one")
        .rename(columns={"Forecast Demand": "Forecasted Demand"})
    )
    # Replenishment's approved fallback is not silently promoted to an MCA fact.
    if not mca_use_lead_time_fallback:
        criteria.loc[criteria["Supplier Lead Time Source"].ne("Per-SKU Supplier Lead Time"), "Supplier Lead Time"] = np.nan
    criteria["Profit Margin"] = np.nan
    criteria["Profit Margin Status"] = "Unavailable: reconciled net-sales/cost ledger and measurement period required"
    if has_period and mca_financial_lines is not None:
        margins = calculate_profit_margin(mca_financial_lines, period_start=start, period_end=end)
        criteria = criteria.drop(columns=["Profit Margin", "Profit Margin Status"]).merge(margins, on="SKU", how="left", validate="one_to_one")
    criteria["Profit Margin Status"] = criteria["Profit Margin Status"].fillna(
        "Unavailable: no source rows for this SKU in the measurement period"
    )
    criteria["MCA Period Start"] = start if has_period else pd.NaT
    criteria["MCA Period End"] = end if has_period else pd.NaT
    active_criteria = MCA_CRITERIA
    request_review = pd.DataFrame()
    sensitivity = pd.DataFrame()
    if mca_coverage is not None:
        from three_criterion_mca import CRITERIA, REQUIRED, evaluate_requests, rank_scenarios
        mca_coverage.validate()
        assessment_end = pd.Timestamp(mca_coverage.order_end).normalize()
        if prepared["Time"].dt.normalize().max() > assessment_end:
            raise ValueError("Three-criterion historical assessment requires sales/analytics/forecasts restricted to its order-date endpoint")
        snapshot = mca_return_snapshot if mca_return_snapshot is not None else pd.DataFrame(columns=REQUIRED)
        return_audit, request_review = evaluate_requests(transactions, snapshot, mapped, mca_coverage)
        criteria = criteria.merge(return_audit.drop(columns="product_key"), on="SKU", how="left", validate="one_to_one")
        active_criteria = CRITERIA
    valid = criteria[list(active_criteria)].apply(pd.to_numeric, errors="coerce").apply(np.isfinite)
    criteria["MCA Eligible"] = valid.all(axis=1)
    criteria["MCA Status"] = [
        "Ready" if complete else "Unavailable: " + ", ".join(valid.columns[~row])
        for complete, (_, row) in zip(criteria["MCA Eligible"], valid.iterrows())
    ]
    mca_audit = criteria[["SKU", "Product", "Category", *active_criteria, "Supplier Lead Time Source",
                          "MCA Period Start", "MCA Period End", "Profit Margin Status",
                          "MCA Eligible", "MCA Status"]].copy()
    if mca_coverage is not None:
        scenarios, sensitivity, diagnostic = rank_scenarios(criteria)
        if mca_weight_scenario not in scenarios:
            raise ValueError("Unknown MCA weight scenario")
        mca = scenarios[mca_weight_scenario]
        for column in ("Eligible Ordered Units", "Recorded Refunded Units", "Return Review Status"):
            mca_audit[column] = criteria[column]
        mca_audit["Approval Status"] = ("TA-approved equal-weight baseline; historical validation accepted"
            if mca_weight_scenario == "equal_thirds" else "Sensitivity comparison only; not the approved baseline")
        mca_audit = mca_audit.drop(columns=["Supplier Lead Time Source", "Profit Margin Status"])
    else:
        mca = calculate_mca_scores(
            criteria.loc[criteria["MCA Eligible"], ["SKU", *MCA_CRITERIA]], identifier_columns=["SKU"]
        )

    recommendation = risk.loc[risk["Current Stock"].notna()].merge(
        mca.drop(columns=["Supplier Lead Time"], errors="ignore"),
        on="SKU", how="left", validate="one_to_one"
    )
    recommendation["Safety Stock"] = recommendation["Forecast Demand"].map(
        lambda demand: calculate_safety_stock(
            demand, forecast_horizon_days=forecast_horizon_days,
            safety_stock_days=REPLENISHMENT_CONFIG.safety_stock_days,
        )
    )
    recommendation["Target Stock Level"] = [
        calculate_target_stock_level(
            demand,
            forecast_horizon_days=forecast_horizon_days,
            lead_time_days=int(lead_time),
            review_period_days=REPLENISHMENT_CONFIG.review_period_days,
            safety_stock_days=REPLENISHMENT_CONFIG.safety_stock_days,
        )
        for demand, lead_time in zip(
            recommendation["Forecast Demand"], recommendation["Supplier Lead Time"]
        )
    ]
    recommendation["Recommended Quantity"] = [
        calculate_replenishment_quantity(target, stock)
        for target, stock in zip(recommendation["Target Stock Level"], recommendation["Current Stock"])
    ]
    recommendation["Recommendation"] = [
        recommendation_action(quantity, risk_level, mca_level)
        for quantity, risk_level, mca_level in zip(
            recommendation["Recommended Quantity"], recommendation["Stock-Out Risk"],
            recommendation["Priority Level"],
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
                f"{row['Supplier Lead Time']:g} lead + "
                f"{REPLENISHMENT_CONFIG.review_period_days} review days, plus "
                f"{REPLENISHMENT_CONFIG.safety_stock_days} "
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
        "mca_audit": mca_audit,
        "recommendation_results": recommendation,
        "return_request_review": request_review,
        "mca_sensitivity": sensitivity,
    }
