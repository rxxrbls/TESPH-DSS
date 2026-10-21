"""Compatibility exports for the central, authoritative MCA methodology."""

from methodology_config import (
    MCA_CRITERIA,
    MCA_DIRECTIONS,
    MCA_WEIGHT_RATIONALE,
    MCA_WEIGHTS,
)
from prescriptive_calculations import (
    calculate_mca_scores,
    calculate_priority_score as _calculate_priority_score,
    calculate_sku_priority as _calculate_sku_priority,
    calculate_weighted_contributions as _calculate_weighted_contributions,
    min_max_normalize as _min_max_normalize,
    rank_priority_scores,
)


MCA_CRITERIA = list(MCA_CRITERIA)

# KAN-259 - CONNECT SALES PERFORMANCE INPUT TO MCA
def connect_sales_performance_to_mca(
    sales_velocity_df,
):
    """
    Converts the existing Sales Velocity analytics output
    into the sales_velocity input required by MCA.

    Expected upstream columns:
        Product Key
        Sales Velocity
    """

    required_columns = {
        "Product Key",
        "Sales Velocity",
    }

    missing_columns = (
        required_columns - set(sales_velocity_df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing Sales Performance columns: "
            f"{missing_columns}"
        )

    mca_sales_input = sales_velocity_df[
        [
            "Product Key",
            "Sales Velocity",
        ]
    ].copy()

    mca_sales_input = mca_sales_input.rename(
        columns={
            "Product Key": "product_key",
            "Sales Velocity": "sales_velocity",
        }
    )

    return mca_sales_input

# KAN-260 - CONNECT FORECASTED DEMAND INPUT TO MCA
def connect_forecasted_demand_to_mca(
    forecast_output_df,
):
    """
    Converts the existing forecasting pipeline output
    into the forecasted_demand input required by MCA.

    Expected upstream columns:
        Category
        Forecast
    """

    required_columns = {
        "Category",
        "Forecast",
    }

    missing_columns = (
        required_columns - set(forecast_output_df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing Forecasted Demand columns: "
            f"{missing_columns}"
        )

    mca_forecast_input = forecast_output_df[
        [
            "Category",
            "Forecast",
        ]
    ].copy()

    mca_forecast_input = mca_forecast_input.rename(
        columns={
            "Category": "category",
            "Forecast": "forecasted_demand",
        }
    )

    return mca_forecast_input

# KAN-261 - CONNECT STOCK-OUT FREQUENCY INPUT TO MCA
def connect_stock_out_frequency_to_mca(
    stock_out_frequency_df,
):
    """
    Legacy adapter for historical auditing only.
    Stock-Out Frequency is no longer used in active MCA scoring.

    Expected upstream columns:
        product_key
        stock_out_frequency
    """

    required_columns = {
        "product_key",
        "stock_out_frequency",
    }

    missing_columns = (
        required_columns - set(stock_out_frequency_df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing Stock-Out Frequency columns: "
            f"{missing_columns}"
        )

    mca_stock_out_input = stock_out_frequency_df[
        [
            "product_key",
            "stock_out_frequency",
        ]
    ].copy()

    return mca_stock_out_input

# KAN-263 - CONNECT RETURN/ORDER INDICATORS INPUT TO MCA
def connect_return_order_indicators_to_mca(
    return_indicators_df,
):
    """
    Converts unit-based return measures to a percentage
    into the return_rate input required by MCA.

    Expected upstream columns:
        Product Key
        Returned Quantity
        Gross Demand
    """

    required_columns = {
        "Product Key",
        "Returned Quantity",
        "Gross Demand",
    }

    missing_columns = (
        required_columns - set(return_indicators_df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing Return/Order Indicator columns: "
            f"{missing_columns}"
        )

    mca_return_input = return_indicators_df[
        [
            "Product Key",
            "Returned Quantity",
            "Gross Demand",
        ]
    ].copy()

    mca_return_input = mca_return_input.rename(
        columns={
            "Product Key": "product_key",
        }
    )

    from mca_inputs import calculate_return_rate
    mca_return_input["return_rate"] = calculate_return_rate(
        mca_return_input["Returned Quantity"], mca_return_input["Gross Demand"]
    )
    return mca_return_input[["product_key", "return_rate"]]

# W1-54 / KAN-131 - TA-APPROVED MCA BENEFIT/COST DIRECTIONS
def validate_mca_configuration():
    """
    Validates the configured MCA methodology.

    Checks that all five criteria have valid directions and weights
    and that the weights sum to 1.00.
    """

    if set(MCA_DIRECTIONS) != set(MCA_CRITERIA):
        raise ValueError("MCA directions must cover exactly the configured criteria")
    if set(MCA_WEIGHTS) != set(MCA_CRITERIA):
        raise ValueError("MCA weights must cover exactly the configured criteria")
    if any(direction not in {"benefit", "cost"} for direction in MCA_DIRECTIONS.values()):
        raise ValueError("MCA directions must be benefit or cost")
    if any(weight < 0 for weight in MCA_WEIGHTS.values()) or round(sum(MCA_WEIGHTS.values()), 6) != 1.0:
        raise ValueError("MCA weights must be non-negative and sum to 1.00")
    return True

# W1-55 / KAN-132 - IMPLEMENT MIN-MAX NORMALIZATION
def min_max_normalize(
    value,
    min_value,
    max_value,
    direction,
):
    """
    Applies Min-Max normalization.

    Benefit:
        (value - min_value) / (max_value - min_value)

    Cost:
        (max_value - value) / (max_value - min_value)
    """

    return _min_max_normalize(value, min_value, max_value, direction)

# NORMALIZE ALL FIVE MCA CRITERIA
def normalize_sku(
    sku_values,
    dataset_minimums,
    dataset_maximums,
):
    normalized_scores = {}

    for criterion in MCA_CRITERIA:
        if criterion not in sku_values:
            raise ValueError(f"Missing value for: {criterion}")

        if criterion not in dataset_minimums:
            raise ValueError(f"Missing minimum value for: {criterion}")

        if criterion not in dataset_maximums:
            raise ValueError(f"Missing maximum value for: {criterion}")

        normalized_scores[criterion] = _min_max_normalize(
            sku_values[criterion], dataset_minimums[criterion],
            dataset_maximums[criterion], MCA_DIRECTIONS[criterion],
        )

    return normalized_scores

# W1-57 / KAN-134 - CALCULATE WEIGHTED CONTRIBUTIONS
def calculate_weighted_contributions(
    normalized_scores,
    weights=None,
):
    """
    Calculates:

        Weighted Contribution =
        Normalized Score x Weight
    """

    return _calculate_weighted_contributions(normalized_scores, weights)


# W1-58 / KAN-134 - CALCULATE MCA PRIORITY SCORE
def calculate_priority_score(
    weighted_contributions,
):
    """
    Calculates:

        Priority Score =
        Sum of weighted contributions
    """

    return _calculate_priority_score(weighted_contributions)


# COMPLETE MCA CALCULATION
def calculate_sku_priority(
    sku_values,
    dataset_minimums,
    dataset_maximums,
):
    """
    Performs the complete MCA calculation for one SKU.

    Steps:
        1. Normalize the five criteria
        2. Calculate weighted contributions
        3. Calculate Priority Score
    """

    validate_mca_configuration()
    return _calculate_sku_priority(sku_values, dataset_minimums, dataset_maximums)


# W1-59 / KAN-135 - IMPLEMENT MCA PRODUCT RANKING
def rank_skus(df, score_column="SKU Priority Score", identifier_columns=None):
    """
    Ranks SKUs from highest to lowest Priority Score.

    Higher Priority Score indicates higher priority
    within the MCA ranking.
    """

    if identifier_columns is None:
        identifier_columns = [column for column in ("SKU", "sku") if column in df.columns]
    if not identifier_columns:
        raise ValueError("Ranking requires an SKU identifier for deterministic ties")
    return rank_priority_scores(
        df, identifier_columns=identifier_columns, score_column=score_column
    )
