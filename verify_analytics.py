"""Run invariant checks against the real ETL outputs without changing them."""

from pathlib import Path

import numpy as np
import pandas as pd

from analytics_calculations import (
    assemble_star_schema_transactions,
    calculate_product_performance,
    calculate_sales_summary,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "final_outputs"


def main() -> None:
    prepared = pd.read_csv(OUTPUT_DIR / "prepared_transactions.csv", low_memory=False)
    summary = calculate_sales_summary(prepared).iloc[0]

    completed = prepared["is_completed"].astype(str).str.casefold().eq("true")
    returned = prepared["is_returned"].astype(str).str.casefold().eq("true")
    demand_mask = completed | returned
    quantity = pd.to_numeric(prepared["Quantity"], errors="raise")
    returned_quantity = pd.to_numeric(
        prepared["Returned quantity"], errors="coerce"
    ).fillna(0.0)
    buyer_payment = pd.to_numeric(prepared["Total Buyer Payment"], errors="raise")

    assert np.isclose(summary["Gross Revenue"], buyer_payment.where(completed, 0).sum())
    assert np.isclose(summary["Gross Demand"], quantity.where(demand_mask, 0).sum())
    expected_net_demand = (
        quantity.where(demand_mask, 0) - returned_quantity.where(demand_mask, 0)
    ).clip(lower=0)
    assert np.isclose(summary["Net Inventory Demand"], expected_net_demand.sum())

    fact = pd.read_csv(OUTPUT_DIR / "fact_sales.csv", low_memory=False)
    dim_order = pd.read_csv(OUTPUT_DIR / "dim_order.csv", low_memory=False)
    dim_product = pd.read_csv(OUTPUT_DIR / "dim_product.csv", low_memory=False)
    dim_date = pd.read_csv(OUTPUT_DIR / "dim_date.csv", low_memory=False)
    star_transactions = assemble_star_schema_transactions(
        fact, dim_order, dim_product, dim_date
    )
    star_summary = calculate_sales_summary(star_transactions).iloc[0]
    for metric in ("Gross Revenue", "Gross Demand", "Net Inventory Demand"):
        assert np.isclose(summary[metric], star_summary[metric])

    products = calculate_product_performance(prepared)
    assert len(products) == prepared["product_key"].nunique(dropna=True)
    assert products["Product Key"].is_unique

    display_metrics = [
        "First Transaction Time",
        "Last Transaction Time",
        "Order Count",
        "Product Count",
        "Category Count",
        "Gross Demand",
        "Returned Quantity",
        "Net Inventory Demand",
        "Gross Revenue",
        "Net Revenue After Returns",
        "Average Order Value",
    ]
    print(summary[display_metrics].to_frame(name="Value").to_string())
    print(f"\nProduct rows: {len(products)}")
    print("Prepared/star-schema totals: MATCH")
    print("REAL-DATA VERIFICATION: PASS")


if __name__ == "__main__":
    main()
