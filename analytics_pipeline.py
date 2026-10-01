"""Descriptive analytics pipeline using professor-confirmed parameters.

This module orchestrates the analytical calculations with the approved
methodology values. It connects the individual calculation functions from
analytics_calculations with the confirmed parameters from methodology_config.

No Streamlit code. All public functions return pandas DataFrames.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from analytics_calculations import (
    calculate_cancellation_indicators,
    calculate_low_sales_threshold,
    calculate_kpis,
    calculate_order_status_indicators,
    calculate_product_movement_metrics,
    calculate_product_performance,
    calculate_return_indicators,
    calculate_sales_summary,
    calculate_sales_trends,
    calculate_sales_velocity,
    calculate_yoy_revenue_growth,
    classify_product_movement,
    exclude_incomplete_latest_month,
    identify_products_for_review,
    prepare_transactions,
)
from analytics_data import load_transactions
from methodology_config import (
    DEMAND_DEFINITION,
    MOVEMENT_FAST_MIN_POSITIVE_PERIODS,
    MOVEMENT_FREQUENCY,
    MOVEMENT_RECENT_PERIODS,
    MOVEMENT_REGULAR_MIN_POSITIVE_PERIODS,
    TREND_FREQUENCY,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "final_outputs"


def _complete_month_end(coverage_end: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if coverage_end is None:
        return None
    cutoff = pd.Timestamp(coverage_end).normalize()
    period = cutoff.to_period("M")
    if cutoff < period.end_time.normalize():
        period -= 1
    return period.end_time.normalize()


def run_product_movement_analysis(
    transactions: pd.DataFrame,
    *, coverage_end: str | pd.Timestamp | None = None,
) -> dict[str, pd.DataFrame]:
    """KAN-36: Calculate product movement with confirmed thresholds.

    Returns a dict with 'metrics', 'classified', 'thresholds', and 'for_review'.
    """
    complete_transactions = exclude_incomplete_latest_month(transactions, coverage_end=coverage_end)
    metrics = calculate_product_movement_metrics(
        complete_transactions,
        frequency=MOVEMENT_FREQUENCY,
        recent_periods=MOVEMENT_RECENT_PERIODS,
        demand_definition=DEMAND_DEFINITION,
        as_of=_complete_month_end(coverage_end),
    )

    # Compute dynamic low-sales threshold per category
    thresholds_df = calculate_low_sales_threshold(metrics)

    # For classification, we need a single threshold per product.
    # Merge the category threshold into the metrics.
    metrics_with_threshold = metrics.merge(
        thresholds_df, on="Category", how="left"
    )
    # Default threshold for categories with no positive demand products
    metrics_with_threshold["Low Sales Threshold"] = (
        pd.to_numeric(metrics_with_threshold["Low Sales Threshold"], errors="raise").fillna(0.0)
    )

    # Classify each product using its category's threshold
    classified_parts = []
    for category, group in metrics_with_threshold.groupby(
        "Category", dropna=False, sort=True, observed=False
    ):
        cat_threshold = group["Low Sales Threshold"].iloc[0]
        cat_classified = classify_product_movement(
            group.drop(columns=["Low Sales Threshold"]),
            low_sales_max_recent_demand=float(cat_threshold),
            regular_moving_min_positive_periods=MOVEMENT_REGULAR_MIN_POSITIVE_PERIODS,
            fast_moving_min_positive_periods=MOVEMENT_FAST_MIN_POSITIVE_PERIODS,
        )
        classified_parts.append(cat_classified)

    if classified_parts:
        classified = pd.concat(classified_parts, ignore_index=True)
    else:
        classified = pd.DataFrame()

    for_review = classified.loc[
        classified["Review Status"].eq("For Business-Owner Review")
    ].reset_index(drop=True) if not classified.empty else pd.DataFrame()

    return {
        "metrics": metrics,
        "classified": classified,
        "thresholds": thresholds_df,
        "for_review": for_review,
    }


def run_analytics_pipeline(
    transactions: pd.DataFrame | None = None,
    *, coverage_end: str | pd.Timestamp | None = None,
) -> dict[str, pd.DataFrame]:
    """Run the full descriptive analytics pipeline with confirmed parameters.

    KAN-31: Sales summary
    KAN-32: Product performance
    KAN-33: Sales trends (monthly)
    KAN-34: Return indicators
    KAN-35: Order status indicators
    KAN-36: Product movement classification
    KAN-37: KPIs
    KAN-38: Products for review
    KAN-39: All outputs are DataFrames
    """
    if transactions is None:
        transactions = load_transactions()

    results: dict[str, pd.DataFrame] = {}

    # KAN-31
    results["sales_summary"] = calculate_sales_summary(transactions)

    # KAN-32
    results["product_performance"] = calculate_product_performance(transactions)

    # KAN-33: Sales trends at approved monthly frequency
    results["sales_trends"] = calculate_sales_trends(
        transactions, frequency=TREND_FREQUENCY
    )

    # KAN-34
    results["return_indicators"] = calculate_return_indicators(transactions)
    results["return_indicators_by_category"] = calculate_return_indicators(
        transactions, group_by=["Category"]
    )

    # KAN-35
    results["order_status"] = calculate_order_status_indicators(transactions)
    results["cancellations"] = calculate_cancellation_indicators(transactions)

    # KAN-36 and KAN-38: Product movement and review
    movement = run_product_movement_analysis(transactions, coverage_end=coverage_end)
    results["movement_metrics"] = movement["metrics"]
    results["movement_classified"] = movement["classified"]
    results["low_sales_thresholds"] = movement["thresholds"]
    results["products_for_review"] = movement["for_review"]

    # KAN-37: KPIs
    results["kpis"] = calculate_kpis(transactions)

    # KAN-37: Sales velocity at approved window
    complete_recent_transactions = exclude_incomplete_latest_month(transactions, coverage_end=coverage_end)
    results["sales_velocity"] = calculate_sales_velocity(
        complete_recent_transactions,
        frequency=MOVEMENT_FREQUENCY,
        recent_periods=MOVEMENT_RECENT_PERIODS,
        demand_definition=DEMAND_DEFINITION,
        as_of=_complete_month_end(coverage_end),
    )

    # KAN-37: YoY revenue growth (use latest complete month)
    prepared = prepare_transactions(complete_recent_transactions)
    latest_month = _complete_month_end(coverage_end) if coverage_end is not None else prepared["Time"].max()
    if pd.notna(latest_month):
        through_month = int(latest_month.month)
        results["yoy_growth"] = calculate_yoy_revenue_growth(
            transactions, through_month=through_month
        )

    return results


if __name__ == "__main__":
    print("Running descriptive analytics pipeline...")
    results = run_analytics_pipeline()
    for name, df in results.items():
        print(f"\n{name}: {len(df)} rows, {list(df.columns)[:5]}...")
    summary = results["sales_summary"].iloc[0]
    print(f"\nGross Revenue: PHP {summary['Gross Revenue']:,.2f}")
    print(f"Gross Demand: {summary['Gross Demand']:,.0f} units")
    print(f"Products for review: {len(results['products_for_review'])}")
    print(f"Movement classifications: {results['movement_classified']['Movement Classification'].value_counts().to_dict() if not results['movement_classified'].empty else 'N/A'}")
    print("\nDESCRIPTIVE ANALYTICS PIPELINE: COMPLETE")
