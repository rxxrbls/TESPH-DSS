import pytest
import pandas as pd
from analytics.derived_metrics import DerivedMetricsCalculator

def test_gross_revenue():
    fact_sales = pd.DataFrame({
        "Order ID": ["O1", "O2", "O3"],
        "Total Buyer Payment": [100.0, 200.0, 150.0],
        "Quantity": [2, 1, 3],
        "Returned quantity": [0, 0, 0],
        "is_cancelled": [False, False, True]
    })
    
    dim_order = pd.DataFrame({
        "Order ID": ["O1", "O2", "O3"],
        "Order Status": ["Completed", "Returned", "Cancelled"]
    })
    
    calc = DerivedMetricsCalculator(fact_sales, dim_order)
    df_gross = calc.get_gross_revenue()
    
    assert len(df_gross) == 1
    assert df_gross.iloc[0]["Order ID"] == "O1"
    assert df_gross.iloc[0]["gross_revenue"] == 100.0

def test_gross_demand():
    fact_sales = pd.DataFrame({
        "Order ID": ["O1", "O2", "O3"],
        "Quantity": [2, 1, 3],
        "is_cancelled": [False, False, True]
    })
    
    dim_order = pd.DataFrame({
        "Order ID": ["O1", "O2", "O3"],
        "Order Status": ["Completed", "Returned", "Cancelled"],
        "Return / Refund Status": ["", "Returned", ""]
    })
    
    calc = DerivedMetricsCalculator(fact_sales, dim_order)
    df_demand = calc.get_gross_demand()
    
    assert len(df_demand) == 2
    assert "O1" in df_demand["Order ID"].values
    assert "O2" in df_demand["Order ID"].values
    assert df_demand[df_demand["Order ID"] == "O1"]["gross_demand"].iloc[0] == 2
    assert df_demand[df_demand["Order ID"] == "O2"]["gross_demand"].iloc[0] == 1

def test_net_revenue_and_inventory():
    fact_sales = pd.DataFrame({
        "Order ID": ["O1", "O2"],
        "Total Buyer Payment": [100.0, 200.0],
        "Quantity": [5, 4],
        "Returned quantity": [2, None], # 2 returned for O1, None for O2
        "is_cancelled": [False, False]
    })
    
    dim_order = pd.DataFrame({
        "Order ID": ["O1", "O2"],
        "Order Status": ["Completed", "Completed"]
    })
    
    calc = DerivedMetricsCalculator(fact_sales, dim_order)
    df_net = calc.get_net_revenue_and_inventory()
    
    assert len(df_net) == 2
    assert df_net[df_net["Order ID"] == "O1"]["net_quantity"].iloc[0] == 3
    assert df_net[df_net["Order ID"] == "O2"]["net_quantity"].iloc[0] == 4

def test_pending_formulas_raise_error():
    calc = DerivedMetricsCalculator(pd.DataFrame(), pd.DataFrame())
    
    with pytest.raises(NotImplementedError):
        calc.calculate_sales_velocity()
        
    with pytest.raises(NotImplementedError):
        calc.calculate_dsi()

    with pytest.raises(NotImplementedError):
        calc.calculate_stockout_frequency()
