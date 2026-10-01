import pandas as pd

from src.prescriptive.mca import (
    connect_sales_performance_to_mca,
)


def test_sales_performance_connects_to_mca():
    sales_velocity_df = pd.DataFrame(
        {
            "Product Key": [
                "prd_001",
                "prd_002",
            ],
            "Sales Velocity": [
                12.5,
                8.0,
            ],
            "Velocity Period Count": [
                3,
                3,
            ],
        }
    )

    result = connect_sales_performance_to_mca(
        sales_velocity_df
    )

    assert "product_key" in result.columns
    assert "sales_velocity" in result.columns

    assert result.loc[0, "product_key"] == "prd_001"
    assert result.loc[0, "sales_velocity"] == 12.5

    assert result.loc[1, "product_key"] == "prd_002"
    assert result.loc[1, "sales_velocity"] == 8.0