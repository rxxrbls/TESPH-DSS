import pandas as pd
import pytest

from src.prescriptive.mca import (
    connect_return_order_indicators_to_mca,
)


def test_return_order_indicators_connect_to_mca():
    return_indicators = pd.DataFrame(
        {
            "Product Key": ["prd_001", "prd_002"],
            "Return Order Rate": [0.10, 0.25],
        }
    )

    result = connect_return_order_indicators_to_mca(
        return_indicators
    )

    assert list(result.columns) == [
        "product_key",
        "return_rate",
    ]

    assert result.loc[0, "product_key"] == "prd_001"
    assert result.loc[0, "return_rate"] == pytest.approx(0.10)

    assert result.loc[1, "product_key"] == "prd_002"
    assert result.loc[1, "return_rate"] == pytest.approx(0.25)


def test_missing_return_order_columns_raise_error():
    invalid_input = pd.DataFrame(
        {
            "Product Key": ["prd_001"],
        }
    )

    with pytest.raises(
        ValueError,
        match="Missing Return/Order Indicator columns",
    ):
        connect_return_order_indicators_to_mca(
            invalid_input
        )