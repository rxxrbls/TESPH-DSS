import pytest

from src.prescriptive.mca import (
    MCA_WEIGHTS,
    calculate_weighted_contributions,
    calculate_priority_score,
)


# KAN-266 - VALIDATE CONFIGURED MCA WEIGHTS AND WEIGHTED SCORES


def test_equal_mca_weights():
    assert MCA_WEIGHTS == {criterion: 1 / 6 for criterion in MCA_WEIGHTS}


def test_weights_sum_to_one():
    assert sum(MCA_WEIGHTS.values()) == pytest.approx(1.00)


def test_weighted_contributions():
    normalized_scores = {
        "Sales Velocity": 0.80,
        "Gross Revenue": 0.60,
        "Supplier Lead Time": 0.70,
        "Projected Stock-Out Risk": 0.50,
        "Forecasted Demand": 0.90,
        "Return Rate": 0.40,
    }

    contributions = calculate_weighted_contributions(
        normalized_scores
    )

    assert contributions["Sales Velocity"] == pytest.approx(0.8 / 6)
    assert contributions["Gross Revenue"] == pytest.approx(0.6 / 6)
    assert contributions["Supplier Lead Time"] == pytest.approx(0.7 / 6)
    assert contributions["Projected Stock-Out Risk"] == pytest.approx(0.5 / 6)
    assert contributions["Forecasted Demand"] == pytest.approx(0.9 / 6)
    assert contributions["Return Rate"] == pytest.approx(0.4 / 6)


def test_final_weighted_score():
    normalized_scores = {
        "Sales Velocity": 0.80,
        "Gross Revenue": 0.60,
        "Supplier Lead Time": 0.70,
        "Projected Stock-Out Risk": 0.50,
        "Forecasted Demand": 0.90,
        "Return Rate": 0.40,
    }

    contributions = calculate_weighted_contributions(
        normalized_scores
    )

    priority_score = calculate_priority_score(
        contributions
    )

    assert priority_score == pytest.approx(0.65)