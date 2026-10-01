import pytest

from src.prescriptive.mca import (
    MCA_CRITERIA,
    MCA_DIRECTIONS,
    MCA_WEIGHT_RATIONALE,
    MCA_WEIGHTS,
    validate_mca_configuration,
)


# KAN-268 - VERIFY CONFIGURED MCA METHODOLOGY


def test_final_mca_criteria():
    assert MCA_CRITERIA == [
        "Sales Velocity",
        "Gross Revenue",
        "Supplier Lead Time",
        "Projected Stock-Out Risk",
        "Forecasted Demand",
        "Return Rate",
    ]


def test_final_mca_directions():
    assert MCA_DIRECTIONS == {
        "Sales Velocity": "benefit",
        "Gross Revenue": "benefit",
        "Supplier Lead Time": "cost",
        "Projected Stock-Out Risk": "cost",
        "Forecasted Demand": "benefit",
        "Return Rate": "cost",
    }


def test_final_mca_weights():
    assert MCA_WEIGHTS == {criterion: 1 / 6 for criterion in MCA_CRITERIA}
    assert MCA_WEIGHT_RATIONALE


def test_weights_sum_to_one():
    assert sum(MCA_WEIGHTS.values()) == pytest.approx(1.00)


def test_mca_configuration_is_valid():
    assert validate_mca_configuration() is True