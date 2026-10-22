"""Week 2 SKU forecasts, nested temporal validation, and bottom-up totals.

Historical product keys are join identifiers, never fabricated SKUs. Forecasts
require explicit client approval or fresh, unambiguous current-catalog evidence.
"""

from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from analytics_calculations import (
    _clean_text,
    _require_columns,
    exclude_incomplete_latest_month,
    prepare_transactions,
)
from analytics_data import load_transactions
from forecasting_calculations import (
    calculate_forecast_metrics,
    evaluate_category_eligibility,
    exponential_smoothing,
    forecast_values,
    linear_regression,
    moving_average,
    prepare_forecasting_dataset,
    select_best_forecast_method,
)
from methodology_config import (
    CATEGORY_ASSESSMENT_WINDOW,
    DEMAND_CONTRIBUTION_WEIGHT,
    FORECAST_DEMAND_DEFINITION,
    ForecastConfig,
    MINIMUM_COMPLETENESS,
    MINIMUM_CONSISTENCY,
    MINIMUM_HISTORY_PERIODS,
    REVENUE_CONTRIBUTION_WEIGHT,
)


MAPPING_COLUMNS = ["product_key", "SKU", "Product", "Category", "active", "category_active", "client_approved"]
HISTORY_COLUMNS = ["Time", "Product Key", "SKU", "Product", "Category", "Demand", "Revenue", "Observed"]
DETAIL_COLUMNS = ["SKU", "Product", "Category", "Origin", "Time", "Step", "Method", "Actual", "Forecast", "MA Window", "ES Alpha"]
CATEGORY_VALIDATION_COLUMNS = ["Category", "Time", "Method", "Actual", "Forecast"]
METRIC_COLUMNS = ["SKU", "Product", "Category", "Method", "MAE", "RMSE", "MAPE", "Raw MAPE", "R2", "Validation Observations", "Zero Actual Count", "MAPE Status"]
FORECAST_COLUMNS = ["SKU", "Product", "Category", "Time", "Forecast", "Method", "MA Window", "ES Alpha", "MAE", "RMSE", "MAPE", "Raw MAPE", "MAPE Status", "Selection Basis", "R2"]
METHODS = ("Moving Average", "Exponential Smoothing", "Linear Regression")


def mapping_template(transactions: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_transactions(transactions)
    result = frame[["Product Key", "SKU", "Product", "Category"]].drop_duplicates()
    # Multiple source SKU values for one key require an explicit reconciliation.
    result = result.groupby(["Product Key", "Product", "Category"], dropna=False)["SKU"].agg(
        lambda s: s.dropna().iloc[0] if s.dropna().nunique() == 1 else pd.NA
    ).reset_index().rename(columns={"Product Key": "product_key"})
    for column in ("active", "category_active", "client_approved"):
        result[column] = False
    return result[MAPPING_COLUMNS]


def validate_mapping(mapping: pd.DataFrame) -> pd.DataFrame:
    _require_columns(mapping, MAPPING_COLUMNS)
    optional = [c for c in ("catalog_active", "Eligibility Basis", "Stock As-Of Date") if c in mapping]
    result = mapping[MAPPING_COLUMNS + optional].copy()
    if "catalog_active" not in result:
        result["catalog_active"] = False
    for column in ("product_key", "SKU", "Product", "Category"):
        result[column] = _clean_text(result[column])
    if result["product_key"].isna().any() or result["product_key"].duplicated().any():
        raise ValueError("Mapping requires exactly one row per nonempty product_key")
    for column in ("active", "category_active", "client_approved", "catalog_active"):
        values = result[column].astype("string").str.strip().str.lower()
        if not values.isin(["true", "false", "1", "0"]).all():
            raise ValueError(f"{column} must explicitly contain true/false or 1/0")
        result[column] = values.isin(["true", "1"])
    approved = result["client_approved"] | result["catalog_active"]
    if result.loc[approved, ["SKU", "Product", "Category"]].isna().any().any():
        raise ValueError("Client-approved mappings require SKU, Product, and Category")
    for _, group in result.loc[result["SKU"].notna()].groupby("SKU"):
        if any(group[c].nunique(dropna=False) > 1 for c in ("Product", "Category", "active", "category_active", "client_approved", "catalog_active")):
            raise ValueError("Each SKU must have one consistent product, category, and eligibility state")
    if (result.groupby("Category")["category_active"].nunique() > 1).any():
        raise ValueError("Category activity must be consistent across its mapping rows")
    return result


def prepare_sku_history(
    transactions: pd.DataFrame, config: ForecastConfig,
    *, coverage_end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Aggregate per historical variation, filling zeros only after first sighting.

    coverage_end is the last fully observed calendar date from the export, not
    the current date. Without it, the last transaction date is a conservative
    bound; a partial final month is excluded in monthly mode.
    """
    frame = prepare_transactions(transactions)
    if frame.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    if frame[["Time", "Product Key", "Product", "Category"]].isna().any().any():
        raise ValueError("Forecast history requires valid dates, product keys, products, and categories")
    if not np.isfinite(frame[["Gross Demand", "Gross Revenue"]].to_numpy(dtype=float)).all():
        raise ValueError("Forecast demand and revenue must be finite")
    cutoff = pd.Timestamp(coverage_end).normalize() if coverage_end is not None else frame["Time"].max().normalize()
    if pd.isna(cutoff):
        raise ValueError("coverage_end must be a valid date")
    period = cutoff.to_period(config.frequency)
    if cutoff < period.end_time.normalize():
        period -= 1
    frame = frame.loc[frame["Time"].dt.to_period(config.frequency).le(period)].copy()
    if frame.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    frame["Time"] = frame["Time"].dt.to_period(config.frequency).dt.to_timestamp()
    parts = []
    for key, group in frame.groupby("Product Key", sort=True):
        if group["Product"].nunique() != 1 or group["Category"].nunique() != 1:
            raise ValueError(f"Conflicting product/category metadata for {key}")
        observed = group.groupby("Time").agg(Demand=("Gross Demand", "sum"), Revenue=("Gross Revenue", "sum"))
        periods = pd.period_range(group["Time"].min().to_period(config.frequency), period, freq=config.frequency).to_timestamp()
        data = observed.reindex(periods)
        data["Observed"] = data["Demand"].notna()
        data[["Demand", "Revenue"]] = data[["Demand", "Revenue"]].fillna(0.0)
        data["Product Key"] = key
        skus = group["SKU"].dropna().unique()
        data["SKU"] = skus[0] if len(skus) == 1 else pd.NA
        data["Product"] = group["Product"].iloc[0]
        data["Category"] = group["Category"].iloc[0]
        parts.append(data.rename_axis("Time").reset_index())
    return pd.concat(parts, ignore_index=True)[HISTORY_COLUMNS]


def _predict(data: pd.DataFrame, method: str, config: ForecastConfig, window: int, alpha: float, horizon: int) -> pd.DataFrame:
    arguments = dict(frequency=config.frequency, horizon=horizon)
    if method == "Moving Average":
        return moving_average(data, window=window, **arguments)
    if method == "Exponential Smoothing":
        return exponential_smoothing(data, alpha=alpha, **arguments)
    return linear_regression(data, **arguments)


def tune_parameters(train: pd.DataFrame, config: ForecastConfig) -> tuple[int, float, pd.DataFrame]:
    """Compare parameters on common inner holdout dates, using training only."""
    # Reserve at least one inner target, even for short histories.
    inner_horizon = min(config.horizon, max(1, len(train) - min(config.windows)))
    windows = sorted({w for w in config.windows if w <= len(train) - inner_horizon})
    if not windows:
        raise ValueError("Insufficient training history to validate an MA window")
    last = len(train) - inner_horizon
    first = max(max(windows), last - config.tuning_periods + 1)
    candidates = [("Moving Average", w, np.nan) for w in windows]
    candidates += [("Exponential Smoothing", 0, a) for a in sorted(set(config.es_alphas))]
    scores = []
    values = train["Demand"].to_numpy(dtype=float)
    for method, window, alpha in candidates:
        errors = []
        actuals = []
        if method == "Exponential Smoothing":
            levels = np.empty(len(values))
            levels[0] = values[0]
            for j in range(1, len(values)):
                levels[j] = alpha * values[j] + (1 - alpha) * levels[j - 1]
        for i in range(first, last + 1):
            prediction = (np.repeat(levels[i - 1], inner_horizon) if method == "Exponential Smoothing"
                          else forecast_values(values[:i], method, inner_horizon, window=window))
            target = values[i:i + inner_horizon]
            errors.extend(target - prediction)
            actuals.extend(target)
        actuals = np.asarray(actuals)
        errors = np.asarray(errors)
        mape = (float(np.mean(np.abs(errors) / np.maximum(actuals, config.mape_denominator_floor)) * 100)
                if config.mape_zero_policy == "denominator_floor" else
                np.nan if (actuals == 0).any() else float(np.mean(np.abs(errors) / actuals) * 100))
        scores.append({"Method": method, "MA Window": window if window else np.nan,
                       "ES Alpha": alpha, "RMSE": float(np.sqrt(np.mean(np.square(errors)))),
                       "MAE": float(np.mean(np.abs(errors))), "MAPE": mape,
                       "Tuning Observations": len(errors), "Tuning Horizon": inner_horizon,
                       "Tuning End": train["Time"].iloc[-1]})
    scores = pd.DataFrame(scores).sort_values(
        [config.primary_metric, config.secondary_metric, "MA Window", "ES Alpha"], kind="stable"
    )
    scores["Selection Basis"] = "Adjusted MAPE, RMSE" if config.mape_zero_policy == "denominator_floor" else (
        "RMSE fallback: MAPE undefined" if scores["MAPE"].isna().all() else "MAPE, RMSE")
    window = int(scores.loc[scores["Method"].eq("Moving Average"), "MA Window"].iloc[0])
    # Identical holdout counts make minimizing RMSE equivalent to minimizing SSE.
    es = scores.loc[scores["Method"].eq("Exponential Smoothing")].sort_values(
        ["RMSE", "MAE", "ES Alpha"], kind="stable")
    alpha = float(es["ES Alpha"].iloc[0])
    scores.loc[scores["Method"].eq("Exponential Smoothing"), "Selection Basis"] = "SSE (RMSE), MAE"
    return window, alpha, scores.reset_index(drop=True)


def backtest_sku(data: pd.DataFrame, config: ForecastConfig) -> pd.DataFrame:
    """All three methods share expanding origins and the same holdout horizon."""
    rows = []
    last_origin = len(data) - config.horizon
    first_origin = max(config.minimum_training_periods, last_origin - config.validation_periods + 1)
    for origin in range(first_origin, last_origin + 1):
        train = data.iloc[:origin]
        window, alpha, _ = tune_parameters(train, config)
        actual = data.iloc[origin:origin + config.horizon]
        for method in METHODS:
            forecast = _predict(train, method, config, window, alpha, config.horizon)
            if not forecast["Time"].reset_index(drop=True).equals(actual["Time"].reset_index(drop=True)):
                raise ValueError("Validation forecast dates must match the complete holdout calendar")
            for step, ((_, target), (_, prediction)) in enumerate(zip(actual.iterrows(), forecast.iterrows()), 1):
                rows.append({"SKU": data["SKU"].iloc[0], "Product": data["Product"].iloc[0],
                             "Category": data["Category"].iloc[0], "Origin": train["Time"].iloc[-1],
                             "Time": target["Time"], "Step": step, "Method": method,
                             "Actual": target["Demand"], "Forecast": prediction["Forecast"],
                             "MA Window": window if method == "Moving Average" else np.nan,
                             "ES Alpha": alpha if method == "Exponential Smoothing" else np.nan})
    return pd.DataFrame(rows, columns=DETAIL_COLUMNS)


def sku_metrics(detail: pd.DataFrame, config: ForecastConfig) -> pd.DataFrame:
    parts = []
    for sku, group in detail.groupby("SKU", sort=True):
        metrics = calculate_forecast_metrics(
            group, mape_zero_actual_policy=config.mape_zero_policy,
            mape_denominator_floor=config.mape_denominator_floor,
        )
        counts = group.groupby("Method").agg(
            **{"Validation Observations": ("Actual", "size"), "Zero Actual Count": ("Actual", lambda s: int(s.eq(0).sum()))}
        ).reset_index()
        metrics = metrics.merge(counts, on="Method", validate="one_to_one")
        raw = calculate_forecast_metrics(group, mape_zero_actual_policy="return_nan")
        metrics = metrics.merge(raw[["Method", "MAPE"]].rename(columns={"MAPE": "Raw MAPE"}),
                                on="Method", validate="one_to_one")
        metrics["SKU"] = sku
        metrics["Product"] = group["Product"].iloc[0]
        metrics["MAPE Status"] = np.where(metrics["Zero Actual Count"].gt(0), "Undefined: zero actual demand", "Defined")
        if config.mape_zero_policy == "denominator_floor":
            metrics["MAPE Status"] = f"Adjusted denominator floor: {config.mape_denominator_floor}"
        parts.append(metrics)
    return pd.concat(parts, ignore_index=True)[METRIC_COLUMNS] if parts else pd.DataFrame(columns=METRIC_COLUMNS)


def run_sku_forecasting(
    transactions: pd.DataFrame | None = None, *, mapping: pd.DataFrame | None = None,
    config: ForecastConfig | None = None, coverage_end: str | pd.Timestamp | None = None,
) -> dict[str, pd.DataFrame]:
    config = config or ForecastConfig()
    config.validate()
    default_data = transactions is None
    transactions = load_transactions() if transactions is None else transactions
    inventory_review = pd.DataFrame()
    if default_data and mapping is None:
        from active_inventory import build_active_mapping
        mapping, inventory_review = build_active_mapping(transactions)
    # Expand calendars only for mapped candidates, but retain every source key
    # in the exclusion report and preserve the full export's coverage boundary.
    history_source = transactions
    if mapping is not None:
        mapping = validate_mapping(mapping)
        candidates = mapping.loc[mapping["active"] & mapping["category_active"] &
                                 (mapping["client_approved"] | mapping["catalog_active"]), "product_key"]
        history_source = transactions.loc[transactions["product_key"].astype("string").isin(candidates)]
    coverage_end = coverage_end if coverage_end is not None else pd.to_datetime(transactions["order_date"]).max()
    history = prepare_sku_history(history_source, config, coverage_end=coverage_end)
    results = {
        "forecasting_dataset": history, "sku_dataset": pd.DataFrame(columns=HISTORY_COLUMNS),
        "validation_detail": pd.DataFrame(columns=DETAIL_COLUMNS),
        "category_validation_detail": pd.DataFrame(columns=CATEGORY_VALIDATION_COLUMNS),
        "validation_metrics": pd.DataFrame(columns=METRIC_COLUMNS),
        "best_methods": pd.DataFrame(columns=METRIC_COLUMNS),
        "forecast_output": pd.DataFrame(columns=FORECAST_COLUMNS),
        "product_forecast": pd.DataFrame(columns=["Product", "Category", "Time", "Forecast"]),
        "category_forecast": pd.DataFrame(columns=["Category", "Time", "Forecast"]),
        "category_eligibility": pd.DataFrame(),
        "parameter_search": pd.DataFrame(columns=["SKU", "Method", "MA Window", "ES Alpha", "RMSE", "MAE"]),
        "methodology": pd.DataFrame([{"Parameter": k, "Value": str(v)} for k, v in asdict(config).items()]),
        "inventory_review": inventory_review,
    }
    category_history = prepare_forecasting_dataset(
        exclude_incomplete_latest_month(transactions, coverage_end=coverage_end),
        frequency="M",
        demand_definition=FORECAST_DEMAND_DEFINITION,
    )
    results["category_eligibility"] = evaluate_category_eligibility(
        category_history,
        assessment_window=CATEGORY_ASSESSMENT_WINDOW,
        minimum_history_periods=MINIMUM_HISTORY_PERIODS,
        minimum_completeness=MINIMUM_COMPLETENESS,
        minimum_consistency=MINIMUM_CONSISTENCY,
        demand_contribution_weight=DEMAND_CONTRIBUTION_WEIGHT,
        revenue_contribution_weight=REVENUE_CONTRIBUTION_WEIGHT,
    )
    keys = mapping_template(transactions).rename(columns={"product_key": "Product Key"})[
        ["Product Key", "SKU", "Product", "Category"]
    ]
    eligibility = keys.rename(columns={"SKU": "Source SKU"})
    if mapping is None:
        eligibility["SKU"] = pd.NA
        eligibility["Eligible"] = False
        eligibility["Reason"] = "Client-approved SKU/category mapping required"
        results["eligibility"] = eligibility
    else:
        approved = validate_mapping(mapping)
        source_keys = set(transactions["product_key"].astype("string"))
        if not set(approved["product_key"]).issubset(source_keys):
            raise ValueError("Mapping contains product keys absent from the ETL handoff")
        eligibility = eligibility.merge(
            approved.rename(columns={"product_key": "Product Key", "Product": "Mapped Product", "Category": "Mapped Category"}),
            on="Product Key", how="left", validate="one_to_one",
        )
        eligibility["Reason"] = np.select(
            [eligibility["SKU"].isna(), ~(eligibility["client_approved"].eq(True) | eligibility["catalog_active"].eq(True)),
             ~eligibility["category_active"].eq(True), ~eligibility["active"].eq(True),
             ~eligibility["Product Key"].isin(history["Product Key"])],
            ["Missing SKU mapping", "Not client-approved", "Inactive category", "Inactive SKU", "No complete history"],
            default="Eligible",
        )
        eligibility["Eligible"] = eligibility["Reason"].eq("Eligible")
        eligible_map = eligibility.loc[eligibility["Eligible"], ["Product Key", "SKU", "Mapped Product", "Mapped Category"]]
        mapped = history.drop(columns=["SKU", "Product", "Category"]).merge(eligible_map, on="Product Key", validate="many_to_one")
        mapped = mapped.rename(columns={"Mapped Product": "Product", "Mapped Category": "Category"})
        sku_data = mapped.groupby(["SKU", "Product", "Category", "Time"], sort=True).agg(
            Demand=("Demand", "sum"), Revenue=("Revenue", "sum"), Observed=("Observed", "any")
        ).reset_index()
        results["sku_dataset"] = sku_data
        details, forecasts, winners, searches = [], [], [], []
        for sku, data in sku_data.groupby("SKU", sort=True):
            data = data.sort_values("Time").reset_index(drop=True)
            detail = backtest_sku(data, config)
            if detail.empty:
                selected = eligibility["SKU"].eq(sku)
                eligibility.loc[selected, "Eligible"] = False
                eligibility.loc[selected, "Reason"] = "Insufficient history for training and holdout horizon"
                continue
            details.append(detail)
            metrics = sku_metrics(detail, config)
            winner = select_best_forecast_method(metrics, primary_metric=config.primary_metric, secondary_metric=config.secondary_metric)
            if config.mape_zero_policy == "denominator_floor":
                winner["Selection Basis"] = "Adjusted MAPE, RMSE"
            winners.append(winner)
            window, alpha, search = tune_parameters(data, config)
            searches.append(search.assign(SKU=sku))
            method = winner["Method"].iloc[0]
            forecast = _predict(data, method, config, window, alpha, config.horizon)
            forecast["SKU"] = sku
            forecast["Product"] = data["Product"].iloc[0]
            forecast["MA Window"] = window if method == "Moving Average" else np.nan
            forecast["ES Alpha"] = alpha if method == "Exponential Smoothing" else np.nan
            for metric in ("MAE", "RMSE", "MAPE", "Raw MAPE", "MAPE Status", "Selection Basis", "R2"):
                forecast[metric] = winner[metric].iloc[0]
            forecasts.append(forecast)
        results["eligibility"] = eligibility
        if details:
            results["validation_detail"] = pd.concat(details, ignore_index=True)
            results["category_validation_detail"] = (
                results["validation_detail"]
                .groupby(["Category", "Time", "Method"], as_index=False)[["Actual", "Forecast"]]
                .sum()
            )[CATEGORY_VALIDATION_COLUMNS]
            results["validation_metrics"] = sku_metrics(results["validation_detail"], config)
            results["best_methods"] = pd.concat(winners, ignore_index=True)[METRIC_COLUMNS + ["Selection Basis"]]
            results["parameter_search"] = pd.concat(searches, ignore_index=True)
            output = pd.concat(forecasts, ignore_index=True)[FORECAST_COLUMNS]
            results["forecast_output"] = output
            results["product_forecast"] = output.groupby(["Product", "Category", "Time"], as_index=False)["Forecast"].sum()
            results["category_forecast"] = output.groupby(["Category", "Time"], as_index=False)["Forecast"].sum()
    output = results["forecast_output"]
    results["selection_status"] = pd.DataFrame([{
        "Status": "Ready" if not output.empty else "No eligible SKU forecasts",
        "Forecast SKU Count": output["SKU"].nunique(),
        "Methodology Status": "TA constraints with documented team implementation decisions",
        "Approval Reference": config.approval_reference,
        "History Coverage End": coverage_end,
        "Forecast End": output["Time"].max() if not output.empty else pd.NaT,
        "Historical Only": bool(not output.empty and output["Time"].max().normalize() < pd.Timestamp.today().normalize()),
    }])
    return results
