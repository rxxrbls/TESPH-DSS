import pytest
import pandas as pd

from src.prescriptive.mca import (
    MCA_WEIGHTS,
    calculate_sku_priority,
    rank_skus,
)


# KAN-136 - VALIDATE MCA METHODOLOGY


def test_equal_weights_have_no_unsubstantiated_differences():
    assert MCA_WEIGHTS == {criterion: 1 / 5 for criterion in MCA_WEIGHTS}

    assert sum(MCA_WEIGHTS.values()) == pytest.approx(1.0)


def test_normalized_values_and_priority_score():
    sku_values = {
        "Sales Velocity": 60,
        "Profit Margin": 40,
        "Supplier Lead Time": 10,
        "Forecasted Demand": 80,
        "Return Rate": 4,
    }

    dataset_minimums = {
        "Sales Velocity": 20,
        "Profit Margin": 20,
        "Supplier Lead Time": 5,
        "Forecasted Demand": 40,
        "Return Rate": 2,
    }

    dataset_maximums = {
        "Sales Velocity": 100,
        "Profit Margin": 60,
        "Supplier Lead Time": 15,
        "Forecasted Demand": 120,
        "Return Rate": 10,
    }

    result = calculate_sku_priority(
        sku_values,
        dataset_minimums,
        dataset_maximums,
    )

    # Expected normalized values:
    # Benefit criteria = 0.50
    # Return Rate (Cost) = 0.75

    assert result["normalized_scores"]["Sales Velocity"] == 0.5
    assert result["normalized_scores"]["Profit Margin"] == 0.5
    assert result["normalized_scores"]["Supplier Lead Time"] == 0.5
    assert result["normalized_scores"]["Forecasted Demand"] == 0.5
    assert result["normalized_scores"]["Return Rate"] == 0.75

    # Expected weighted score:
    # Four criteria score 0.50 and Return Rate scores 0.75, all weighted 20%.

    assert result["priority_score"] == pytest.approx(0.55)


def test_weighted_contributions():
    sku_values = {
        "Sales Velocity": 60,
        "Profit Margin": 40,
        "Supplier Lead Time": 10,
        "Forecasted Demand": 80,
        "Return Rate": 4,
    }

    dataset_minimums = {
        "Sales Velocity": 20,
        "Profit Margin": 20,
        "Supplier Lead Time": 5,
        "Forecasted Demand": 40,
        "Return Rate": 2,
    }

    dataset_maximums = {
        "Sales Velocity": 100,
        "Profit Margin": 60,
        "Supplier Lead Time": 15,
        "Forecasted Demand": 120,
        "Return Rate": 10,
    }

    result = calculate_sku_priority(
        sku_values,
        dataset_minimums,
        dataset_maximums,
    )

    contributions = result["weighted_contributions"]

    assert contributions["Sales Velocity"] == pytest.approx(1 / 10)
    assert contributions["Profit Margin"] == pytest.approx(1 / 10)
    assert contributions["Supplier Lead Time"] == pytest.approx(1 / 10)
    assert contributions["Forecasted Demand"] == pytest.approx(1 / 10)
    assert contributions["Return Rate"] == pytest.approx(0.15)


def test_product_ranking():
    df = pd.DataFrame({
        "sku": ["SKU-A", "SKU-B", "SKU-C"],
        "SKU Priority Score": [0.525, 0.800, 0.300],
    })

    ranked = rank_skus(df, identifier_columns=["sku"])

    assert ranked.iloc[0]["sku"] == "SKU-B"
    assert ranked.iloc[0]["Priority Rank"] == 1

    assert ranked.iloc[1]["sku"] == "SKU-A"
    assert ranked.iloc[1]["Priority Rank"] == 2

    assert ranked.iloc[2]["sku"] == "SKU-C"
    assert ranked.iloc[2]["Priority Rank"] == 3