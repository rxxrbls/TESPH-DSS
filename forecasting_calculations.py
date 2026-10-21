"""Reusable forecasting calculations for KAN-41 through KAN-53.

Forecast frequency, horizon, model parameters, validation policy, and category
eligibility thresholds are explicit inputs. No Streamlit code or invented
business values belong in this module.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from analytics_calculations import (
    _demand_values,
    _normalise_frequency,
    _require_columns,
    prepare_transactions,
)


FORECAST_COLUMNS = ["Time", "Category", "Forecast", "Method"]
FINAL_FORECAST_COLUMNS = ["Category", "Forecast", "Method", "MAE", "RMSE", "MAPE", "R2"]
MAX_FORECAST_CATEGORIES = 3


def _validate_positive_integer(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer from the approved methodology")


def _validate_forecasting_data(data: pd.DataFrame) -> pd.DataFrame:
    _require_columns(data, ["Time", "Demand", "Category"])
    result = data.copy()
    result["Time"] = pd.to_datetime(result["Time"], errors="coerce")
    result["Demand"] = pd.to_numeric(result["Demand"], errors="coerce")
    if result[["Time", "Demand", "Category"]].isna().any().any():
        raise ValueError("Time, Demand, and Category must not contain missing values")
    if not np.isfinite(result["Demand"]).all() or result["Demand"].lt(0).any():
        raise ValueError("Demand must be finite and cannot be negative")
    return result.sort_values(["Category", "Time"], kind="stable").reset_index(drop=True)


def _future_times(last_time: pd.Timestamp, frequency: str, horizon: int) -> pd.DatetimeIndex:
    last_period = last_time.to_period(frequency)
    return pd.period_range(last_period + 1, periods=horizon, freq=frequency).to_timestamp()


def _forecast_each_category(
    data: pd.DataFrame,
    *,
    frequency: str,
    horizon: int,
    method: str,
    forecaster: Callable[[np.ndarray, int], np.ndarray],
) -> pd.DataFrame:
    frequency = _normalise_frequency(frequency)
    _validate_positive_integer(horizon, "horizon")
    clean = _validate_forecasting_data(data)
    rows: list[dict[str, object]] = []
    for category, group in clean.groupby("Category", dropna=False, sort=True):
        values = group["Demand"].to_numpy(dtype=float)
        predictions = np.asarray(forecaster(values, horizon), dtype=float)
        if len(predictions) != horizon:
            raise ValueError(f"{method} returned {len(predictions)} values for horizon {horizon}")
        predictions = np.maximum(predictions, 0.0)
        for time, prediction in zip(
            _future_times(group["Time"].max(), frequency, horizon), predictions
        ):
            rows.append(
                {
                    "Time": time,
                    "Category": category,
                    "Forecast": prediction,
                    "Method": method,
                }
            )
    return pd.DataFrame(rows, columns=FORECAST_COLUMNS)


def prepare_forecasting_dataset(
    transactions: pd.DataFrame,
    *,
    frequency: str,
    demand_definition: str = "gross_demand",
) -> pd.DataFrame:
    """KAN-41: convert transactions to continuous Time/Demand/Category history."""

    frequency = _normalise_frequency(frequency)
    frame = prepare_transactions(transactions).dropna(subset=["Time", "Category"])
    if frame.empty:
        return pd.DataFrame(columns=["Time", "Demand", "Revenue", "Category", "Observed"])
    frame["Demand"] = _demand_values(frame, demand_definition)
    frame["Revenue for Forecasting"] = frame["Gross Revenue"]
    frame["Period"] = frame["Time"].dt.to_period(frequency)
    observed = (
        frame.groupby(["Period", "Category"], dropna=False, sort=True, observed=False)
        .agg(Demand=("Demand", "sum"), Revenue=("Revenue for Forecasting", "sum"))
        .reset_index()
    )
    observed["Observed"] = True
    periods = pd.period_range(observed["Period"].min(), observed["Period"].max(), freq=frequency)
    categories = observed["Category"].drop_duplicates().sort_values(kind="stable")
    complete_index = pd.MultiIndex.from_product(
        [periods, categories], names=["Period", "Category"]
    ).to_frame(index=False)
    result = complete_index.merge(observed, on=["Period", "Category"], how="left")
    result[["Demand", "Revenue"]] = result[["Demand", "Revenue"]].fillna(0.0)
    result["Observed"] = result["Observed"].eq(True)
    result["Time"] = result["Period"].dt.to_timestamp()
    return result[["Time", "Demand", "Revenue", "Category", "Observed"]]


def define_forecast_period(
    forecasting_data: pd.DataFrame,
    *,
    frequency: str,
    horizon: int,
) -> pd.DataFrame:
    """KAN-42: create future periods only from an explicitly supplied horizon."""

    frequency = _normalise_frequency(frequency)
    _validate_positive_integer(horizon, "horizon")
    clean = _validate_forecasting_data(forecasting_data)
    rows: list[dict[str, object]] = []
    for category, group in clean.groupby("Category", dropna=False, sort=True):
        for step, time in enumerate(
            _future_times(group["Time"].max(), frequency, horizon), start=1
        ):
            rows.append({"Time": time, "Category": category, "Forecast Step": step})
    return pd.DataFrame(rows, columns=["Time", "Category", "Forecast Step"])


def forecast_values(values: np.ndarray, method: str, horizon: int, *, window: int = 3, alpha: float = 0.5) -> np.ndarray:
    """Shared numeric model kernels for public forecasts and nested tuning."""
    _validate_positive_integer(horizon, "horizon")
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("History must contain finite nonnegative demand")
    if method == "Moving Average":
        _validate_positive_integer(window, "window")
        if len(values) < window:
            raise ValueError(f"Moving Average requires at least {window} historical periods")
        history = values.tolist()
        for _ in range(horizon):
            history.append(float(np.mean(history[-window:])))
        return np.asarray(history[-horizon:])
    if method == "Exponential Smoothing":
        if not np.isfinite(alpha) or not 0 < alpha <= 1:
            raise ValueError("alpha must be greater than 0 and at most 1")
        level = float(values[0])
        for value in values[1:]:
            level = alpha * value + (1 - alpha) * level
        return np.repeat(level, horizon)
    if method == "Linear Regression":
        if len(values) < 2:
            raise ValueError("Linear Regression requires at least 2 historical periods")
        slope, intercept = np.polyfit(np.arange(len(values), dtype=float), values, 1)
        return np.maximum(intercept + slope * np.arange(len(values), len(values) + horizon), 0.0)
    raise ValueError(f"Unknown forecasting method: {method}")


def moving_average(data: pd.DataFrame, *, frequency: str, horizon: int, window: int) -> pd.DataFrame:
    _validate_positive_integer(window, "window")
    return _forecast_each_category(data, frequency=frequency, horizon=horizon,
        method="Moving Average", forecaster=lambda values, steps: forecast_values(values, "Moving Average", steps, window=window))


def exponential_smoothing(data: pd.DataFrame, *, frequency: str, horizon: int, alpha: float) -> pd.DataFrame:
    if not np.isfinite(alpha) or not 0 < alpha <= 1:
        raise ValueError("alpha must be greater than 0 and at most 1")
    return _forecast_each_category(data, frequency=frequency, horizon=horizon,
        method="Exponential Smoothing", forecaster=lambda values, steps: forecast_values(values, "Exponential Smoothing", steps, alpha=alpha))


def linear_regression(data: pd.DataFrame, *, frequency: str, horizon: int) -> pd.DataFrame:
    return _forecast_each_category(data, frequency=frequency, horizon=horizon,
        method="Linear Regression", forecaster=lambda values, steps: forecast_values(values, "Linear Regression", steps))


def calculate_seasonal_indices(
    data: pd.DataFrame,
    *,
    frequency: str,
    season_length: int,
) -> pd.DataFrame:
    """Calculate multiplicative seasonal indices from historical demand."""

    frequency = _normalise_frequency(frequency)
    _validate_positive_integer(season_length, "season_length")
    clean = _validate_forecasting_data(data)
    rows: list[dict[str, object]] = []
    for category, group in clean.groupby("Category", dropna=False, sort=True):
        if len(group) < season_length * 2:
            raise ValueError(
                "Seasonal Index Adjustment requires at least two complete seasonal cycles"
            )
        periods = group["Time"].dt.to_period(frequency)
        positions = periods.map(lambda period: period.ordinal % season_length)
        overall_average = float(group["Demand"].mean())
        if np.isclose(overall_average, 0.0):
            indices = pd.Series(1.0, index=range(season_length))
        else:
            indices = group.assign(_position=positions).groupby("_position")["Demand"].mean()
            indices = indices.reindex(range(season_length)) / overall_average
            if indices.isna().any():
                raise ValueError("Historical data does not cover every seasonal position")
            indices = indices / indices.mean()
        for position, seasonal_index in indices.items():
            rows.append(
                {
                    "Category": category,
                    "Season Position": int(position),
                    "Seasonal Index": float(seasonal_index),
                }
            )
    return pd.DataFrame(rows, columns=["Category", "Season Position", "Seasonal Index"])


def seasonal_index_adjustment(
    historical_data: pd.DataFrame,
    baseline_forecast: pd.DataFrame,
    *,
    frequency: str,
    season_length: int,
) -> pd.DataFrame:
    """KAN-46: multiply a baseline model forecast by its seasonal index."""

    _require_columns(baseline_forecast, FORECAST_COLUMNS)
    frequency = _normalise_frequency(frequency)
    indices = calculate_seasonal_indices(
        historical_data, frequency=frequency, season_length=season_length
    )
    result = baseline_forecast.copy()
    result["Time"] = pd.to_datetime(result["Time"], errors="coerce")
    if result["Time"].isna().any():
        raise ValueError("Baseline forecast Time must contain valid dates")
    result["Season Position"] = result["Time"].dt.to_period(frequency).map(
        lambda period: period.ordinal % season_length
    )
    result = result.merge(
        indices,
        on=["Category", "Season Position"],
        how="left",
        validate="many_to_one",
    )
    if result["Seasonal Index"].isna().any():
        raise ValueError("A seasonal index is missing for a forecast category")
    result["Forecast"] = (
        pd.to_numeric(result["Forecast"], errors="coerce") * result["Seasonal Index"]
    ).clip(lower=0.0)
    result["Method"] = result["Method"].astype("string") + " + Seasonal Index"
    return result[FORECAST_COLUMNS]


def align_actual_and_forecast(actual: pd.DataFrame, forecast: pd.DataFrame) -> pd.DataFrame:
    """Align historical holdout demand and forecasts for metric calculations."""

    _require_columns(actual, ["Time", "Category", "Demand"])
    _require_columns(forecast, FORECAST_COLUMNS)
    actual_values = actual[["Time", "Category", "Demand"]].rename(
        columns={"Demand": "Actual"}
    )
    result = actual_values.merge(
        forecast[FORECAST_COLUMNS], on=["Time", "Category"], how="inner", validate="many_to_many"
    )
    result["Actual"] = pd.to_numeric(result["Actual"], errors="coerce")
    result["Forecast"] = pd.to_numeric(result["Forecast"], errors="coerce")
    return result.dropna(subset=["Actual", "Forecast"]).reset_index(drop=True)


def _metric_by_category(
    validation_data: pd.DataFrame,
    metric_name: str,
    calculation: Callable[[np.ndarray, np.ndarray], float],
) -> pd.DataFrame:
    _require_columns(validation_data, ["Category", "Method", "Actual", "Forecast"])
    rows = []
    for group_values, group in validation_data.groupby(
        ["Category", "Method"], dropna=False, sort=True, observed=False
    ):
        actual = pd.to_numeric(group["Actual"], errors="coerce").to_numpy(dtype=float)
        forecast = pd.to_numeric(group["Forecast"], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(actual) & np.isfinite(forecast)
        if not valid.all():
            raise ValueError("Validation actuals and forecasts must be finite; observations cannot be silently dropped")
        if (actual < 0).any() or (forecast < 0).any():
            raise ValueError("Validation demand and forecasts cannot be negative")
        category, method = group_values
        rows.append(
            {
                "Category": category,
                "Method": method,
                metric_name: calculation(actual[valid], forecast[valid]),
            }
        )
    return pd.DataFrame(rows, columns=["Category", "Method", metric_name])


def calculate_mae(validation_data: pd.DataFrame) -> pd.DataFrame:
    """KAN-47: calculate mean absolute error by category and method."""

    return _metric_by_category(
        validation_data,
        "MAE",
        lambda actual, forecast: float(np.mean(np.abs(actual - forecast))) if len(actual) else np.nan,
    )


def calculate_rmse(validation_data: pd.DataFrame) -> pd.DataFrame:
    """KAN-48: calculate root mean squared error by category and method."""

    return _metric_by_category(
        validation_data,
        "RMSE",
        lambda actual, forecast: (
            float(np.sqrt(np.mean(np.square(actual - forecast)))) if len(actual) else np.nan
        ),
    )


def calculate_mape(
    validation_data: pd.DataFrame,
    *,
    zero_actual_policy: str,
    denominator_floor: float | None = None,
) -> pd.DataFrame:
    """KAN-49: calculate MAPE using an explicitly approved zero-actual policy."""

    if zero_actual_policy not in {"exclude", "return_nan", "denominator_floor"}:
        raise ValueError("Unknown zero_actual_policy")
    if zero_actual_policy == "denominator_floor" and (
        denominator_floor is None or not np.isfinite(denominator_floor) or denominator_floor <= 0
    ):
        raise ValueError("denominator_floor must be positive and finite")

    def mape(actual: np.ndarray, forecast: np.ndarray) -> float:
        if zero_actual_policy == "denominator_floor":
            return float(np.mean(np.abs(actual - forecast) / np.maximum(np.abs(actual), denominator_floor)) * 100) if len(actual) else np.nan
        nonzero = actual != 0.0
        if zero_actual_policy == "return_nan" and not nonzero.all():
            return np.nan
        if not nonzero.any():
            return np.nan
        return float(np.mean(np.abs((actual[nonzero] - forecast[nonzero]) / actual[nonzero])) * 100)

    return _metric_by_category(validation_data, "MAPE", mape)


def calculate_r_squared(validation_data: pd.DataFrame) -> pd.DataFrame:
    """KAN-50: calculate the coefficient of determination by category and method."""

    def r_squared(actual: np.ndarray, forecast: np.ndarray) -> float:
        if len(actual) < 2 or np.all(actual == actual[0]):
            return np.nan
        total = float(np.sum(np.square(actual - np.mean(actual))))
        if total == 0.0:
            return np.nan
        residual = float(np.sum(np.square(actual - forecast)))
        return 1 - residual / total

    return _metric_by_category(validation_data, "R2", r_squared)


def calculate_forecast_metrics(
    validation_data: pd.DataFrame,
    *,
    mape_zero_actual_policy: str,
    mape_denominator_floor: float | None = None,
) -> pd.DataFrame:
    """Return MAE, RMSE, MAPE, and R2 in one clean DataFrame."""

    result = calculate_mae(validation_data)
    for metric_frame in (
        calculate_rmse(validation_data),
        calculate_mape(validation_data, zero_actual_policy=mape_zero_actual_policy,
                       denominator_floor=mape_denominator_floor),
        calculate_r_squared(validation_data),
    ):
        result = result.merge(
            metric_frame,
            on=["Category", "Method"],
            how="outer",
            validate="one_to_one",
        )
    return result[["Category", "Method", "MAE", "RMSE", "MAPE", "R2"]]


def evaluate_category_eligibility(
    forecasting_data: pd.DataFrame,
    *,
    assessment_window: int | None = None,
    minimum_history_periods: int,
    minimum_completeness: float,
    minimum_consistency: float,
    demand_contribution_weight: float,
    revenue_contribution_weight: float,
) -> pd.DataFrame:
    """KAN-51: evaluate, rank, and select up to three eligible categories."""

    _require_columns(forecasting_data, ["Time", "Demand", "Revenue", "Category", "Observed"])
    _validate_positive_integer(minimum_history_periods, "minimum_history_periods")
    if assessment_window is None:
        assessment_window = minimum_history_periods
    _validate_positive_integer(assessment_window, "assessment_window")
    if not 0 <= minimum_completeness <= 1:
        raise ValueError("minimum_completeness must be between 0 and 1")
    if not 0 <= minimum_consistency <= 1:
        raise ValueError("minimum_consistency must be between 0 and 1")
    contribution_weights = np.asarray(
        [demand_contribution_weight, revenue_contribution_weight], dtype=float
    )
    if not np.isfinite(contribution_weights).all() or (contribution_weights < 0).any():
        raise ValueError("Contribution weights must be finite and non-negative")
    if not np.isclose(contribution_weights.sum(), 1.0):
        raise ValueError("Demand and revenue contribution weights must sum to 1.00")

    data = forecasting_data.copy()
    data["Time"] = pd.to_datetime(data["Time"], errors="coerce")
    data["Demand"] = pd.to_numeric(data["Demand"], errors="coerce").fillna(0.0)
    data["Revenue"] = pd.to_numeric(data["Revenue"], errors="coerce").fillna(0.0)
    data["Observed"] = data["Observed"].eq(True)
    all_times = pd.Series(data["Time"].dropna().unique()).sort_values(kind="stable")
    assessment_periods = min(int(assessment_window), len(all_times))
    assessment_times = set(all_times.iloc[-assessment_periods:]) if assessment_periods else set()
    output_columns = [
        "Category",
        "Expected Periods",
        "Assessment Periods",
        "Total Historical Periods",
        "Available Periods",
        "Positive-Demand Periods",
        "Historical Completeness",
        "Historical Consistency",
        "Demand",
        "Revenue",
        "Demand Contribution",
        "Revenue Contribution",
        "Contribution",
        "Eligible",
        "Eligibility Reason",
        "Eligibility Rank",
        "Selected",
    ]
    if not assessment_periods:
        return pd.DataFrame(columns=output_columns)

    data["Positive Demand"] = data["Demand"].gt(0).astype(int)
    data["Is Assessment Period"] = data["Time"].isin(assessment_times)

    all_history = (
        data.groupby("Category", dropna=False, sort=True, observed=False)
        .agg(
            **{
                "Total Historical Periods": ("Observed", "sum"),
                "Demand": ("Demand", "sum"),
                "Revenue": ("Revenue", "sum"),
            }
        )
        .reset_index()
    )
    recent_history = (
        data.loc[data["Is Assessment Period"]]
        .groupby("Category", dropna=False, sort=True, observed=False)
        .agg(
            **{
                "Available Periods": ("Observed", "sum"),
                "Positive-Demand Periods": ("Positive Demand", "sum"),
            }
        )
        .reset_index()
    )
    result = all_history.merge(
        recent_history, on="Category", how="left", validate="one_to_one"
    )
    result[["Available Periods", "Positive-Demand Periods"]] = result[
        ["Available Periods", "Positive-Demand Periods"]
    ].fillna(0)
    result.insert(1, "Expected Periods", int(assessment_window))
    result.insert(2, "Assessment Periods", assessment_periods)
    result["Historical Completeness"] = result["Available Periods"] / float(
        assessment_window
    )
    result["Historical Consistency"] = result["Positive-Demand Periods"] / float(
        assessment_window
    )
    enough_history = result["Total Historical Periods"].ge(minimum_history_periods)
    complete = result["Historical Completeness"].ge(minimum_completeness)
    consistent = result["Historical Consistency"].ge(minimum_consistency)
    result["Eligible"] = enough_history & complete & consistent

    eligible_mask = result["Eligible"]
    eligible_demand_total = result.loc[eligible_mask, "Demand"].sum()
    eligible_revenue_total = result.loc[eligible_mask, "Revenue"].sum()
    result["Demand Contribution"] = 0.0
    result["Revenue Contribution"] = 0.0
    if eligible_demand_total:
        result.loc[eligible_mask, "Demand Contribution"] = (
            result.loc[eligible_mask, "Demand"] / eligible_demand_total
        )
    if eligible_revenue_total:
        result.loc[eligible_mask, "Revenue Contribution"] = (
            result.loc[eligible_mask, "Revenue"] / eligible_revenue_total
        )
    result["Contribution"] = (
        demand_contribution_weight * result["Demand Contribution"]
        + revenue_contribution_weight * result["Revenue Contribution"]
    )

    reasons = []
    for history_ok, completeness_ok, consistency_ok in zip(
        enough_history, complete, consistent
    ):
        failures = []
        if not history_ok:
            failures.append("insufficient history")
        if not completeness_ok:
            failures.append("incomplete history")
        if not consistency_ok:
            failures.append("inconsistent demand")
        reasons.append("Eligible" if not failures else "; ".join(failures))
    result["Eligibility Reason"] = reasons
    result["Eligibility Rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    eligible_indices = result.index[result["Eligible"]]
    if len(eligible_indices):
        ranks = result.loc[eligible_indices, "Contribution"].rank(
            method="first", ascending=False
        ).astype("Int64")
        result.loc[eligible_indices, "Eligibility Rank"] = ranks
    result["Selected"] = result["Eligible"] & result["Eligibility Rank"].le(
        MAX_FORECAST_CATEGORIES
    ).fillna(False)
    return result[output_columns].sort_values(
        ["Selected", "Eligible", "Contribution"],
        ascending=[False, False, False],
        kind="stable",
    ).reset_index(drop=True)


def category_selection_status(eligibility: pd.DataFrame) -> pd.DataFrame:
    """KAN-52: return the state for zero, one, two, or three selections."""

    _require_columns(eligibility, ["Eligible", "Selected"])
    eligible_count = int(eligibility["Eligible"].fillna(False).sum())
    selected_count = int(eligibility["Selected"].fillna(False).sum())
    if eligible_count == 0:
        status = "Insufficient Data"
        message = "No category satisfies the approved eligibility rules."
    else:
        status = "Ready"
        noun = "category" if selected_count == 1 else "categories"
        message = f"Forecast all {selected_count} selected eligible {noun}."
    return pd.DataFrame(
        [
            {
                "Status": status,
                "Eligible Category Count": eligible_count,
                "Selected Category Count": selected_count,
                "Message": message,
            }
        ]
    )


def select_best_forecast_method(
    metrics: pd.DataFrame,
    *,
    primary_metric: str,
    secondary_metric: str,
) -> pd.DataFrame:
    """Select one method per category using explicitly approved metric priorities."""

    _require_columns(metrics, ["Category", "Method", primary_metric, secondary_metric])
    result = metrics.copy()
    result[primary_metric] = pd.to_numeric(result[primary_metric], errors="coerce")
    result[secondary_metric] = pd.to_numeric(result[secondary_metric], errors="coerce")
    if np.isinf(result[primary_metric]).any():
        raise ValueError("Infinite primary scores are invalid, not undefined MAPE")
    if result[[primary_metric, secondary_metric]].lt(0).any().any():
        raise ValueError("Selection error scores cannot be negative")
    selected = []
    groups = ["SKU"] if "SKU" in result else ["Category"]
    for _, group in result.groupby(groups, sort=True, dropna=False):
        if not np.isfinite(group[secondary_metric]).all():
            raise ValueError("Every candidate must have a finite secondary selection score")
        primary = np.isfinite(group[primary_metric])
        if primary.any() and not primary.all():
            raise ValueError("Candidate primary scores must share the same validation coverage")
        keys = [primary_metric, secondary_metric, "Method"] if primary.all() else [secondary_metric, "Method"]
        if not primary.all() and primary_metric != "MAPE":
            raise ValueError("Only undefined MAPE supports secondary-metric fallback")
        winner = group.sort_values(keys, kind="stable").head(1).copy()
        winner["Selection Basis"] = f"{primary_metric}, {secondary_metric}, method name" if primary.all() else f"{secondary_metric} fallback: MAPE undefined for all candidates"
        selected.append(winner)
    return pd.concat(selected, ignore_index=True) if selected else result.assign(**{"Selection Basis": pd.Series(dtype=str)})


def format_forecast_output(
    forecasts: pd.DataFrame,
    metrics: pd.DataFrame,
    *,
    forecast_aggregation: str,
) -> pd.DataFrame:
    """KAN-53: return the clean demand-forecast integration fields."""

    _require_columns(forecasts, FORECAST_COLUMNS)
    _require_columns(metrics, ["Category", "Method", "MAE", "RMSE", "MAPE", "R2"])
    aggregations = {"sum": "sum", "mean": "mean", "last": "last"}
    if forecast_aggregation not in aggregations:
        raise ValueError("forecast_aggregation must be sum, mean, or last per the methodology")
    aggregate = (
        forecasts.sort_values("Time", kind="stable")
        .groupby(["Category", "Method"], dropna=False, sort=True, observed=False)["Forecast"]
        .agg(aggregations[forecast_aggregation])
        .reset_index()
    )
    result = aggregate.merge(
        metrics,
        on=["Category", "Method"],
        how="left",
        validate="one_to_one",
    )
    return result[FINAL_FORECAST_COLUMNS]
