import pytest

from src.prescriptive.mca import (
    MCA_WEIGHTS,
    calculate_weighted_contributions,
    calculate_priority_score,
)


# KAN-266 - VALIDATE CONFIGURED MCA WEIGHTS AND WEIGHTED SCORES


def test_equal_mca_weights():
    assert MCA_WEIGHTS == {criterion: 1 / 5 for criterion in MCA_WEIGHTS}


def test_weights_sum_to_one():
    assert sum(MCA_WEIGHTS.values()) == pytest.approx(1.00)


def test_weighted_contributions():
    normalized_scores = {
        "Sales Velocity": 0.80,
        "Profit Margin": 0.60,
        "Supplier Lead Time": 0.70,
        "Forecasted Demand": 0.90,
        "Return Rate": 0.40,
    }

    contributions = calculate_weighted_contributions(
        normalized_scores
    )

    assert contributions["Sales Velocity"] == pytest.approx(0.8 / 5)
    assert contributions["Profit Margin"] == pytest.approx(0.6 / 5)
    assert contributions["Supplier Lead Time"] == pytest.approx(0.7 / 5)
    assert contributions["Forecasted Demand"] == pytest.approx(0.9 / 5)
    assert contributions["Return Rate"] == pytest.approx(0.4 / 5)


def test_final_weighted_score():
    normalized_scores = {
        "Sales Velocity": 0.80,
        "Profit Margin": 0.60,
        "Supplier Lead Time": 0.70,
        "Forecasted Demand": 0.90,
        "Return Rate": 0.40,
    }

    contributions = calculate_weighted_contributions(
        normalized_scores
    )

    priority_score = calculate_priority_score(
        contributions
    )

    assert priority_score == pytest.approx(0.68)