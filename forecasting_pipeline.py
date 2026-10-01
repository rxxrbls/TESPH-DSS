"""Week 2 SKU pipeline entry point and legacy category validation helpers.

Orchestrates: data prep → category eligibility → rolling validation →
alpha grid search → model selection → final forecast → clean output.

No Streamlit code. Returns clean DataFrames.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analytics_calculations import exclude_incomplete_latest_month
from forecasting_calculations import (
    align_actual_and_forecast,
    calculate_forecast_metrics,
    category_selection_status,
    define_forecast_period,
    evaluate_category_eligibility,
    exponential_smoothing,
    format_forecast_output,
    linear_regression,
    moving_average,
    prepare_forecasting_dataset,
    seasonal_index_adjustment,
    select_best_forecast_method,
)
from methodology_config import (
    ForecastConfig,
    CATEGORY_ASSESSMENT_WINDOW,
    DEMAND_CONTRIBUTION_WEIGHT,
    ES_ALPHA_CANDIDATES,
    FORECAST_AGGREGATION,
    FORECAST_DEMAND_DEFINITION,
    FORECAST_FREQUENCY,
    FORECAST_HORIZON,
    MA_WINDOW,
    MAPE_ZERO_ACTUAL_POLICY,
    MINIMUM_COMPLETENESS,
    MINIMUM_CONSISTENCY,
    MINIMUM_HISTORY_PERIODS,
    PRIMARY_SELECTION_METRIC,
    REVENUE_CONTRIBUTION_WEIGHT,
    SEASONAL_CYCLE,
    SECONDARY_SELECTION_METRIC,
    VALIDATION_PERIODS,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "final_outputs"


def _find_best_es_alpha(
    full_data: pd.DataFrame,
    *,
    frequency: str,
    validation_periods: int,
) -> dict[str, float]:
    """Grid-search ES alpha per category using rolling validation RMSE."""

    best_alphas: dict[str, float] = {}
    categories = full_data["Category"].drop_duplicates().sort_values().tolist()

    for category in categories:
        category_data = full_data.loc[full_data["Category"] == category].sort_values(
            "Time", kind="stable"
        )
        all_times = sorted(category_data["Time"].drop_duplicates())
        if len(all_times) < 2:
            best_alphas[category] = ES_ALPHA_CANDIDATES[4]  # default 0.5
            continue

        best_rmse = np.inf
        best_alpha = ES_ALPHA_CANDIDATES[4]
        validation_times = all_times[-min(validation_periods, len(all_times) - 1):]
        for alpha in ES_ALPHA_CANDIDATES:
            errors: list[float] = []
            for val_time in validation_times:
                cat_train = category_data.loc[category_data["Time"] < val_time]
                cat_holdout = category_data.loc[category_data["Time"] == val_time]
                if cat_train.empty or cat_holdout.empty:
                    continue
                try:
                    forecast = exponential_smoothing(
                        cat_train, frequency=frequency, horizon=1, alpha=alpha
                    )
                    aligned = align_actual_and_forecast(cat_holdout, forecast)
                    if aligned.empty:
                        continue
                    errors.extend(
                        (aligned["Actual"] - aligned["Forecast"]).to_numpy(dtype=float)
                    )
                except (ValueError, KeyError):
                    continue
            if not errors:
                continue
            rmse = float(np.sqrt(np.mean(np.square(errors))))
            if rmse < best_rmse:
                best_rmse = rmse
                best_alpha = alpha
        best_alphas[category] = best_alpha

    return best_alphas

def _rolling_validation(
    full_data: pd.DataFrame,
    *,
    frequency: str,
    validation_periods: int,
    ma_window: int,
    best_alphas: dict[str, float],
    seasonal_cycle: int,
) -> pd.DataFrame:
    """Rolling 1-month-ahead validation over the latest N complete months.

    For each validation month:
    1. Train on all data before that month
    2. Forecast 1 month ahead
    3. Compare forecast with actual

    5 candidate methods:
    - Moving Average
    - Exponential Smoothing (best alpha)
    - Linear Regression
    - Moving Average + Seasonal Index
    - Exponential Smoothing + Seasonal Index
    """
    all_times = sorted(full_data["Time"].drop_duplicates())
    if len(all_times) <= validation_periods:
        # Not enough history for rolling validation; use all available
        validation_periods = max(len(all_times) - ma_window - 1, 1)

    validation_times = all_times[-validation_periods:]
    all_validation_rows: list[pd.DataFrame] = []

    for val_time in validation_times:
        train = full_data.loc[full_data["Time"] < val_time].copy()
        actual = full_data.loc[full_data["Time"] == val_time].copy()

        if train.empty or actual.empty:
            continue

        # Never use parameters tuned on the outer holdout or later observations.
        best_alphas = _find_best_es_alpha(
            train, frequency=frequency, validation_periods=validation_periods,
        )

        train_periods = train["Time"].nunique()
        forecasts: list[pd.DataFrame] = []

        # Method 1: Moving Average
        if train_periods >= ma_window:
            try:
                ma_fc = moving_average(
                    train, frequency=frequency, horizon=1, window=ma_window
                )
                forecasts.append(ma_fc)
            except ValueError:
                pass

        # Method 2: Exponential Smoothing (best alpha per category)
        es_fc_parts = []
        for category in train["Category"].drop_duplicates():
            cat_train = train.loc[train["Category"] == category]
            alpha = best_alphas.get(category, 0.5)
            try:
                es_cat = exponential_smoothing(
                    cat_train, frequency=frequency, horizon=1, alpha=alpha
                )
                es_fc_parts.append(es_cat)
            except ValueError:
                pass
        if es_fc_parts:
            es_fc = pd.concat(es_fc_parts, ignore_index=True)
            forecasts.append(es_fc)

        # Method 3: Linear Regression
        if train_periods >= 2:
            try:
                lr_fc = linear_regression(
                    train, frequency=frequency, horizon=1
                )
                forecasts.append(lr_fc)
            except ValueError:
                pass

        # Method 4: MA + Seasonal Index
        if train_periods >= ma_window and train_periods >= seasonal_cycle * 2:
            try:
                ma_base = moving_average(
                    train, frequency=frequency, horizon=1, window=ma_window
                )
                ma_seasonal = seasonal_index_adjustment(
                    train, ma_base,
                    frequency=frequency, season_length=seasonal_cycle
                )
                forecasts.append(ma_seasonal)
            except ValueError:
                pass

        # Method 5: ES + Seasonal Index
        if train_periods >= seasonal_cycle * 2:
            es_seasonal_parts = []
            for category in train["Category"].drop_duplicates():
                cat_train = train.loc[train["Category"] == category]
                alpha = best_alphas.get(category, 0.5)
                if len(cat_train) < seasonal_cycle * 2:
                    continue
                try:
                    es_base = exponential_smoothing(
                        cat_train, frequency=frequency, horizon=1, alpha=alpha
                    )
                    es_adj = seasonal_index_adjustment(
                        cat_train, es_base,
                        frequency=frequency, season_length=seasonal_cycle
                    )
                    es_seasonal_parts.append(es_adj)
                except ValueError:
                    pass
            if es_seasonal_parts:
                forecasts.append(pd.concat(es_seasonal_parts, ignore_index=True))

        # Align forecasts with actuals
        for fc in forecasts:
            aligned = align_actual_and_forecast(actual, fc)
            if not aligned.empty:
                all_validation_rows.append(aligned)

    if not all_validation_rows:
        return pd.DataFrame(
            columns=["Time", "Category", "Method", "Actual", "Forecast"]
        )
    return pd.concat(all_validation_rows, ignore_index=True)


def run_forecasting_pipeline(
    transactions: pd.DataFrame | None = None,
    *,
    mapping: pd.DataFrame | None = None,
    config: "ForecastConfig | None" = None,
    coverage_end: str | pd.Timestamp | None = None,
) -> dict[str, pd.DataFrame]:
    """Week 2 public entry point: forecast SKUs, then aggregate bottom-up."""
    from sku_forecasting import run_sku_forecasting

    return run_sku_forecasting(
        transactions, mapping=mapping, config=config, coverage_end=coverage_end,
    )


if __name__ == "__main__":
    import argparse
    import json
    from methodology_config import ForecastConfig

    parser = argparse.ArgumentParser(description="Run Week 2 SKU forecasting")
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--coverage-end")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    settings = ForecastConfig(**json.loads(args.config.read_text())) if args.config else ForecastConfig()
    mapping = pd.read_csv(args.mapping, dtype={"product_key": "string", "SKU": "string"}) if args.mapping else None
    results = run_forecasting_pipeline(mapping=mapping, config=settings, coverage_end=args.coverage_end)
    print(results["selection_status"].to_string(index=False))
    print(results["eligibility"]["Reason"].value_counts().to_string())
    if args.output_dir:
        if args.output_dir.resolve() == OUTPUT_DIR.resolve():
            parser.error("Use a separate analytics output directory, not the ETL handoff directory")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            frame.to_csv(args.output_dir / (name + ".csv"), index=False)
