import unittest

import pandas as pd

from analytics_calculations import (
    NO_REVIEW_FLAG,
    REVIEW_REQUIRED,
    assemble_star_schema_transactions,
    calculate_low_sales_threshold,
    calculate_net_seller_payout,
    calculate_order_status_indicators,
    calculate_product_performance,
    calculate_return_indicators,
    calculate_sales_summary,
    calculate_sales_velocity,
    calculate_yoy_revenue_growth,
    classify_product_movement,
)


def sample_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Order ID": ["O1", "O2", "O3", "O4", "O5"],
            "Order Status": ["Completed", "Cancelled", "Completed", "Order Received", "Completed"],
            "SKU Reference No.": ["SKU-1", "SKU-1", "SKU-2", pd.NA, "SKU-2"],
            "Product Name": ["Raw P1", "Raw P1", "Raw P2", "Raw P3", "Raw P2"],
            "product_key": ["P1", "P1", "P2", "P3", "P2"],
            "final_base_product_name": ["Product 1", "Product 1", "Product 2", "Product 3", "Product 2"],
            "final_category": ["Category A", "Category A", "Category B", "Category B", "Category B"],
            "order_date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-02-01", "2026-02-02"],
            "Quantity": [2, 3, 4, 1, 2],
            "Returned quantity": [1, 0, 0, 0, 0],
            "Deal Price": [10, 10, 5, 7, 5],
            "Total Buyer Payment": [20, 30, 20, 7, 10],
            "Service Fee": [2, 3, 2, 1, 1],
            "Transaction Fee": [1, 1, 1, 1, 1],
            "is_completed": [True, False, True, False, True],
            "is_cancelled": [False, True, False, False, False],
            "is_returned": [True, False, False, True, False],
        }
    )


class ManualCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transactions = sample_transactions()

    def test_sales_summary_matches_manual_calculation(self) -> None:
        result = calculate_sales_summary(self.transactions).iloc[0]

        self.assertEqual(result["Order Count"], 5)
        self.assertEqual(result["All Ordered Quantity"], 2 + 3 + 4 + 1 + 2)
        self.assertEqual(result["Gross Demand"], 2 + 4 + 1 + 2)
        self.assertEqual(result["Net Inventory Demand"], 1 + 4 + 1 + 2)
        self.assertEqual(result["Cancelled Quantity"], 3)
        self.assertEqual(result["Returned Quantity"], 1)
        self.assertEqual(result["Gross Revenue"], 20 + 20 + 10)
        self.assertEqual(result["Net Revenue After Returns"], 10 + 20 + 10)
        self.assertAlmostEqual(result["Average Order Value"], 50 / 3)
        self.assertAlmostEqual(result["Return Quantity Rate"], 1 / 9)
        self.assertAlmostEqual(result["Cancellation Order Rate"], 1 / 5)

    def test_product_performance_matches_manual_calculation(self) -> None:
        result = calculate_product_performance(self.transactions)
        product = result.loc[result["Product Key"].eq("P1")].iloc[0]

        self.assertEqual(product["SKU"], "SKU-1")
        self.assertEqual(product["Product"], "Product 1")
        self.assertEqual(product["Category"], "Category A")
        self.assertEqual(product["All Order Count"], 2)
        self.assertEqual(product["Gross Demand"], 2)
        self.assertEqual(product["Net Inventory Demand"], 1)
        self.assertEqual(product["Cancelled Quantity"], 3)
        self.assertEqual(product["Returned Quantity"], 1)
        self.assertEqual(product["Gross Revenue"], 20)
        self.assertEqual(product["Net Revenue After Returns"], 10)
        self.assertAlmostEqual(product["Return Quantity Rate"], 1 / 2)

    def test_return_and_status_calculations_match_manual_results(self) -> None:
        returns = calculate_return_indicators(self.transactions).iloc[0]
        statuses = calculate_order_status_indicators(self.transactions)
        cancelled = statuses.loc[statuses["Order Status"].eq("Cancelled")].iloc[0]

        self.assertEqual(returns["Return-Flagged Line Count"], 2)
        self.assertEqual(returns["Returned-Quantity Line Count"], 1)
        self.assertEqual(returns["Return Order Count"], 2)
        self.assertAlmostEqual(returns["Returned-Quantity Line Rate"], 1 / 4)
        self.assertAlmostEqual(returns["Return Order Rate"], 2 / 4)
        self.assertEqual(cancelled["Order Count"], 1)
        self.assertEqual(cancelled["Quantity"], 3)
        self.assertEqual(cancelled["Gross Revenue"], 0)

    def test_net_seller_payout_uses_actual_fee_columns(self) -> None:
        result = calculate_net_seller_payout(
            self.transactions, transaction_fee_column="Transaction Fee"
        ).iloc[0]
        self.assertEqual(result["Net Seller Payout"], (20 - 2 - 1) / 2 + (20 - 2 - 1) + (10 - 1 - 1))

    def test_product_movement_uses_consistent_terms_and_review_flag(self) -> None:
        metrics = pd.DataFrame(
            {
                "SKU": ["A", "B", "C", "D"],
                "Product": ["A", "B", "C", "D"],
                "Category": ["One", "One", "Two", "Two"],
                "Product Key": ["A", "B", "C", "D"],
                "Recent Demand": [60.0, 4.0, 2.0, 0.0],
                "Recent Average Demand": [20.0, 2.0, 2.0, 0.0],
                "Recent Positive-Demand Periods": [3, 2, 1, 0],
            }
        )
        result = classify_product_movement(
            metrics,
            low_sales_max_recent_average=2,
            regular_moving_min_positive_periods=2,
            fast_moving_min_positive_periods=3,
        )

        self.assertEqual(
            result["Movement Classification"].tolist(),
            ["Fast Moving", "Regular Moving", "Slow Moving", "No Movement"],
        )
        self.assertEqual(
            result["Review Status"].tolist(),
            [NO_REVIEW_FLAG, NO_REVIEW_FLAG, REVIEW_REQUIRED, REVIEW_REQUIRED],
        )

    def test_low_sales_threshold_uses_positive_recent_demand(self) -> None:
        metrics = pd.DataFrame(
            {
                "Category": ["One", "One", "One", "Two", "Two"],
                "Recent Demand": [0.0, 4.0, 12.0, 8.0, 24.0],
            }
        )
        result = calculate_low_sales_threshold(metrics).set_index("Category")

        self.assertAlmostEqual(result.loc["One", "Low Sales Threshold"], 6.0)
        self.assertAlmostEqual(result.loc["Two", "Low Sales Threshold"], 12.0)

    def test_velocity_and_yoy_use_explicit_comparable_periods(self) -> None:
        transactions = pd.concat(
            [
                self.transactions.assign(order_date="2025-01-01"),
                self.transactions.assign(
                    **{
                        "Order ID": ["N1", "N2", "N3", "N4", "N5"],
                        "order_date": "2026-01-01",
                        "Total Buyer Payment": [40, 30, 40, 7, 20],
                    }
                ),
            ],
            ignore_index=True,
        )
        velocity = calculate_sales_velocity(
            transactions, frequency="M", recent_periods=1
        )
        yoy = calculate_yoy_revenue_growth(transactions, through_month=1)

        self.assertTrue(velocity["Sales Velocity"].ge(0).all())
        self.assertAlmostEqual(yoy.iloc[-1]["YoY Revenue Growth"], 1.0)

    def test_star_schema_join_uses_order_dimension(self) -> None:
        fact = pd.DataFrame(
            {
                "Order ID": ["O1"],
                "product_key": ["P1"],
                "date_key": [20260101],
                "Quantity": [2],
                "Returned quantity": [0],
                "Deal Price": [10],
                "Total Buyer Payment": [20],
                "is_completed": [True],
                "is_cancelled": [False],
                "is_returned": [False],
            }
        )
        order = pd.DataFrame({"Order ID": ["O1"], "Order Status": ["Completed"]})
        product = pd.DataFrame(
            {
                "product_key": ["P1"],
                "original Product Name": ["Raw P1"],
                "SKU": ["SKU-1"],
                "final_base_product_name": ["Product 1"],
                "final_category": ["Category A"],
            }
        )
        date = pd.DataFrame({"date_key": [20260101], "full_date": ["2026-01-01"]})

        result = assemble_star_schema_transactions(fact, order, product, date)
        self.assertEqual(result.iloc[0]["Order Status"], "Completed")
        self.assertEqual(calculate_sales_summary(result).iloc[0]["Gross Revenue"], 20)


if __name__ == "__main__":
    unittest.main()
