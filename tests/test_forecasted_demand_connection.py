import pandas as pd
import pytest

from src.prescriptive.mca import connect_forecasted_demand_to_mca


def test_connect_forecasted_demand_to_mca():
    forecast_output = pd.DataFrame(
        {
            "Category": ["Kitchenware", "Electronics & Accessories"],
            "Forecast": [120.5, 80.0],
            "Method": ["Moving Average", "Exponential Smoothing"],
            "MAE": [5.0, 4.0],
        }
    )

    result = connect_forecasted_demand_to_mca(
        forecast_output
    )

    assert list(result.columns) == [
        "category",
        "forecasted_demand",
    ]

    assert result["category"].tolist() == [
        "Kitchenware",
        "Electronics & Accessories",
    ]

    assert result["forecasted_demand"].tolist() == [
        120.5,
        80.0,
    ]


def test_connect_forecasted_demand_requires_expected_columns():
    invalid_output = pd.DataFrame(
        {
            "Category": ["Kitchenware"],
        }
    )

    with pytest.raises(
        ValueError,
        match="Missing Forecasted Demand columns",
    ):
        connect_forecasted_demand_to_mca(
            invalid_output
        )