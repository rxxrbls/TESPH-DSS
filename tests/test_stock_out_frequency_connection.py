import pandas as pd
import pytest

from src.prescriptive.mca import (
    connect_stock_out_frequency_to_mca,
)


def test_stock_out_frequency_connects_to_mca():
    stock_out_frequency = pd.DataFrame(
        {
            "product_key": [
                "prd_001",
                "prd_002",
            ],
            "stock_out_frequency": [
                3,
                1,
            ],
        }
    )

    result = connect_stock_out_frequency_to_mca(
        stock_out_frequency
    )

    assert list(result.columns) == [
        "product_key",
        "stock_out_frequency",
    ]

    assert result.loc[0, "product_key"] == "prd_001"
    assert result.loc[0, "stock_out_frequency"] == 3

    assert result.loc[1, "product_key"] == "prd_002"
    assert result.loc[1, "stock_out_frequency"] == 1


def test_stock_out_frequency_requires_expected_columns():
    invalid_input = pd.DataFrame(
        {
            "product_key": ["prd_001"],
        }
    )

    with pytest.raises(
        ValueError,
        match="Missing Stock-Out Frequency columns",
    ):
        connect_stock_out_frequency_to_mca(
            invalid_input
        )