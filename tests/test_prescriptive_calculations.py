import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from methodology_config import STOCK_RISK_THRESHOLDS
from prescriptive_calculations import (
    CURRENT_STOCK_COLUMN,
    DEFAULT_CURRENT_STOCK_PATH,
    MCA_CRITERIA,
    MCA_DIRECTIONS,
    RAW_CURRENT_STOCK_EXPORT_PATH,
    StockRiskThresholds,
    aggregate_current_stock,
    attach_inventory_product_metadata,
    build_inventory_product_crosswalk,
    calculate_mca_scores,
    calculate_stock_out_risk,
    load_current_stock_inventory,
    prepare_current_stock_inventory,
    validate_current_stock_inventory,
)


class StockRiskTests(unittest.TestCase):
    def test_default_doi_thresholds_are_configured(self) -> None:
        self.assertEqual(STOCK_RISK_THRESHOLDS.critical_max_days, 1)
        self.assertEqual(STOCK_RISK_THRESHOLDS.high_max_days, 3)
        self.assertEqual(STOCK_RISK_THRESHOLDS.medium_max_days, 7)

    def test_default_current_stock_path_is_repo_relative_and_loadable(self) -> None:
        self.assertTrue(DEFAULT_CURRENT_STOCK_PATH.is_file())
        self.assertTrue(RAW_CURRENT_STOCK_EXPORT_PATH.is_file())
        self.assertEqual(DEFAULT_CURRENT_STOCK_PATH.suffix, ".csv")
        self.assertEqual(RAW_CURRENT_STOCK_EXPORT_PATH.suffix, ".xlsx")
        self.assertIn("raw_data", DEFAULT_CURRENT_STOCK_PATH.parts)
        self.assertNotIn("mass_update_sales_info", DEFAULT_CURRENT_STOCK_PATH.name)

        inventory = load_current_stock_inventory()

        self.assertEqual(len(inventory), 1980)
        self.assertEqual(int(inventory[CURRENT_STOCK_COLUMN].isna().sum()), 0)
        self.assertEqual(int(inventory[CURRENT_STOCK_COLUMN].lt(0).sum()), 0)
        self.assertEqual(
            inventory["Stock As-Of Date"].dt.strftime("%Y-%m-%d").unique().tolist(),
            ["2026-09-09"],
        )

    def test_current_stock_export_is_cleaned_without_inventing_values(self) -> None:
        export = pd.DataFrame(
            [
                [
                    "et_title_product_id",
                    "et_title_product_name",
                    "et_title_variation_id",
                    "et_title_variation_name",
                    "et_title_parent_sku",
                    "et_title_variation_sku",
                    "et_title_variation_stock",
                ],
                ["sales_info", "metadata", "", "", "", "", ""],
                [
                    "Product ID",
                    "Product Name",
                    "Variation ID",
                    "Variation Name",
                    "Parent SKU",
                    "SKU",
                    "Stock",
                ],
                ["", "", "", "", "", "", "Mandatory"],
                ["P1", "Stress Ball", "V1", "Red", "PARENT-1", "SKU-RED", "5"],
                ["P1", "Stress Ball", "V2", "Blue", "PARENT-1", "SKU-BLUE", "7"],
            ]
        )

        inventory = prepare_current_stock_inventory(
            export,
            stock_as_of_date="2026-09-09",
        )

        self.assertEqual(len(inventory), 2)
        self.assertEqual(inventory[CURRENT_STOCK_COLUMN].tolist(), [5.0, 7.0])
        self.assertTrue(inventory["product_key"].notna().all())
        self.assertEqual(inventory["SKU"].tolist(), ["SKU-RED", "SKU-BLUE"])
        self.assertEqual(
            inventory["Stock As-Of Date"].dt.strftime("%Y-%m-%d").unique().tolist(),
            ["2026-09-09"],
        )

    def test_current_stock_rejects_fractional_counts(self) -> None:
        export = pd.DataFrame(
            [
                ["Product Name", "Variation Name", "SKU", "Stock"],
                ["Desk Fan", "Green", "SKU-GREEN", "1.5"],
            ]
        )

        with self.assertRaisesRegex(ValueError, "whole-number"):
            prepare_current_stock_inventory(export)

    def test_current_stock_export_can_be_loaded_from_xlsx(self) -> None:
        export = pd.DataFrame(
            [
                ["metadata", "", "", ""],
                ["Product Name", "Variation Name", "SKU", "Stock"],
                ["Desk Fan", "Green", "SKU-GREEN", "9"],
            ]
        )

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "current_stock.xlsx"
            export.to_excel(path, index=False, header=False)
            inventory = load_current_stock_inventory(path)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory.iloc[0][CURRENT_STOCK_COLUMN], 9.0)
        self.assertEqual(inventory.iloc[0]["SKU"], "SKU-GREEN")

    def test_current_stock_export_can_be_loaded_from_clean_csv(self) -> None:
        export = pd.DataFrame(
            [
                {
                    "Product Name": "Desk Fan",
                    "Variation Name": "Green",
                    "SKU": "SKU-GREEN",
                    "Current Stock": "9",
                    "Stock As-Of Date": "2026-09-09",
                }
            ]
        )

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "current_stock.csv"
            export.to_csv(path, index=False)
            inventory = load_current_stock_inventory(path)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory.iloc[0][CURRENT_STOCK_COLUMN], 9.0)
        self.assertEqual(inventory.iloc[0]["SKU"], "SKU-GREEN")
        self.assertEqual(
            inventory["Stock As-Of Date"].dt.strftime("%Y-%m-%d").unique().tolist(),
            ["2026-09-09"],
        )

    def test_clean_csv_can_use_existing_category_and_product_key(self) -> None:
        export = pd.DataFrame(
            [
                {
                    "Category": "Kitchenware",
                    "product_key": "prd_existing_key",
                    "Current Stock": "12",
                }
            ]
        )

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "current_stock.csv"
            export.to_csv(path, index=False)
            inventory = load_current_stock_inventory(path)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory.iloc[0]["Category"], "Kitchenware")
        self.assertEqual(inventory.iloc[0]["product_key"], "prd_existing_key")
        self.assertEqual(inventory.iloc[0][CURRENT_STOCK_COLUMN], 12.0)

    def test_current_stock_validation_reports_review_flags(self) -> None:
        inventory = pd.DataFrame(
            {
                "Product ID": ["101", "101"],
                "Variation ID": ["1001", "1001"],
                "Product Name": ["Widget", "Widget"],
                "Variation Name": ["Blue", "Blue"],
                "SKU": ["SKU-1", "SKU-1"],
                CURRENT_STOCK_COLUMN: [5, 7],
            }
        )

        report = validate_current_stock_inventory(inventory)
        checks = report["row_checks"]

        self.assertFalse(report["valid"])
        self.assertTrue(checks["duplicate_product_variation_id"].all())
        self.assertTrue(checks["reused_sku"].all())
        self.assertEqual(report["stock_as_of_status"], "pending_confirmation")

    def test_inventory_crosswalk_recovers_exact_sku_candidate(self) -> None:
        inventory = pd.DataFrame(
            {
                "Product Name": ["Renamed Listing"],
                "Variation Name": ["Blue"],
                "SKU": ["SKU-1"],
                CURRENT_STOCK_COLUMN: [5],
                "Stock As-Of Date": ["2026-09-09"],
            }
        )
        product_dimension = pd.DataFrame(
            {
                "product_key": ["historical-key-1"],
                "final_base_product_name": ["Reviewed Widget"],
                "standardized Product Name": ["widget"],
                "standardized Variation Name": ["blue"],
                "SKU": ["SKU-1"],
                "final_category": ["Category A"],
            }
        )

        result = build_inventory_product_crosswalk(inventory, product_dimension)

        self.assertEqual(result.iloc[0]["crosswalk_product_key"], "historical-key-1")
        self.assertEqual(result.iloc[0]["Candidate Category"], "Category A")
        self.assertEqual(result.iloc[0]["match_method"], "exact_sku")
        self.assertEqual(result.iloc[0]["match_status"], "candidate")
        self.assertFalse(bool(result.iloc[0]["mapping_review_required"]))
        self.assertIn(
            "stock_definition_pending_client_confirmation",
            result.iloc[0]["review_reasons"],
        )

    def test_inventory_crosswalk_flags_product_key_sku_conflict(self) -> None:
        inventory = pd.DataFrame(
            {
                "product_key": ["historical-key-1"],
                "Product Name": ["Widget"],
                "Variation Name": ["Blue"],
                "SKU": ["SKU-2"],
                CURRENT_STOCK_COLUMN: [5],
                "Stock As-Of Date": ["2026-09-09"],
            }
        )
        product_dimension = pd.DataFrame(
            {
                "product_key": ["historical-key-1", "historical-key-2"],
                "final_base_product_name": ["Reviewed Widget", "Reviewed Gadget"],
                "standardized Product Name": ["widget", "gadget"],
                "standardized Variation Name": ["blue", "small"],
                "SKU": ["SKU-1", "SKU-2"],
                "final_category": ["Category A", "Category B"],
            }
        )

        result = build_inventory_product_crosswalk(inventory, product_dimension)

        self.assertTrue(pd.isna(result.iloc[0]["crosswalk_product_key"]))
        self.assertEqual(result.iloc[0]["match_status"], "review_required")
        self.assertTrue(bool(result.iloc[0]["mapping_review_required"]))
        self.assertIn("product_key_sku_conflict", result.iloc[0]["review_reasons"])

    def test_inventory_can_be_aggregated_to_forecast_grain(self) -> None:
        inventory = pd.DataFrame(
            {
                "product_key": ["P1", "P2", "P3"],
                CURRENT_STOCK_COLUMN: [5, 7, 11],
            }
        )
        product_dimension = pd.DataFrame(
            {
                "product_key": ["P1", "P2", "P3"],
                "final_base_product_name": ["Ball", "Cube", "Mug"],
                "final_category": ["Toys", "Toys", "Kitchenware"],
            }
        )

        attached = attach_inventory_product_metadata(inventory, product_dimension)
        result = aggregate_current_stock(attached, item_columns=["Category"])

        by_category = result.set_index("Category")
        self.assertEqual(by_category.loc["Toys", CURRENT_STOCK_COLUMN], 12)
        self.assertEqual(by_category.loc["Kitchenware", CURRENT_STOCK_COLUMN], 11)

    def test_days_of_inventory_risk_index_and_states(self) -> None:
        forecasts = pd.DataFrame(
            {
                "SKU": ["A", "B", "C", "D", "E", "F"],
                "Forecast": [100, 100, 100, 100, 0, 10],
                "Method": ["MA"] * 6,
            }
        )
        inventory = pd.DataFrame(
            {
                "SKU": ["A", "B", "C", "D", "E"],
                "Available Stock": [0, 30, 70, 120, 10],
            }
        )
        result = calculate_stock_out_risk(
            forecasts,
            inventory,
            item_columns=["SKU"],
            current_stock_column="Available Stock",
            forecast_horizon_days=10,
            thresholds=StockRiskThresholds(
                critical_max_days=2,
                high_max_days=5,
                medium_max_days=10,
            ),
        ).set_index("SKU")

        self.assertEqual(result.loc["A", "Days of Inventory"], 0)
        self.assertEqual(result.loc["A", "Risk Index"], 1)
        self.assertEqual(result.loc["A", "Stock-Out Risk"], "Critical")
        self.assertEqual(result.loc["B", "Stock-Out Risk"], "High")
        self.assertEqual(result.loc["C", "Stock-Out Risk"], "Medium")
        self.assertEqual(result.loc["D", "Stock-Out Risk"], "Low")
        self.assertEqual(result.loc["E", "Stock-Out Risk"], "No Forecast Demand")
        self.assertEqual(result.loc["F", "Stock-Out Risk"], "Insufficient Stock Data")

    def test_default_thresholds_classify_using_configured_bands(self) -> None:
        forecasts = pd.DataFrame(
            {
                "Category": ["Toys", "Kitchenware", "Personal Care"],
                "Forecast": [100, 0, 25],
            }
        )
        inventory = pd.DataFrame(
            {
                "Category": ["Toys", "Kitchenware"],
                CURRENT_STOCK_COLUMN: [50, 10],
            }
        )

        result = calculate_stock_out_risk(
            forecasts,
            inventory,
            item_columns=["Category"],
            forecast_horizon_days=10,
        ).set_index("Category")

        self.assertEqual(result.loc["Toys", "Forecast Daily Demand"], 10)
        self.assertEqual(result.loc["Toys", "Days of Inventory"], 5)
        self.assertEqual(result.loc["Toys", "Risk Index"], 0.5)
        self.assertEqual(result.loc["Toys", "Stock-Out Risk"], "Medium")
        self.assertEqual(result.loc["Kitchenware", "Stock-Out Risk"], "No Forecast Demand")
        self.assertEqual(
            result.loc["Personal Care", "Stock-Out Risk"],
            "Insufficient Stock Data",
        )

    def test_stock_thresholds_must_be_ordered(self) -> None:
        with self.assertRaisesRegex(ValueError, "increase"):
            StockRiskThresholds(
                critical_max_days=5,
                high_max_days=3,
                medium_max_days=10,
            ).validate()


class MCATests(unittest.TestCase):
    def test_six_criteria_are_normalized_and_weighted(self) -> None:
        alternatives = pd.DataFrame(
            {
                "SKU": ["A", "B"],
                "Sales Velocity": [100, 50],
                "Gross Revenue": [1000.0, 500.0],
                "Supplier Lead Time": [20, 10],
                "Projected Stock-Out Risk": [0.5, 0.1],
                "Forecasted Demand": [120, 80],
                "Return Rate": [0.1, 0.2],
            }
        )
        weights = {criterion: 1 / len(MCA_CRITERIA) for criterion in MCA_CRITERIA}
        result = calculate_mca_scores(
            alternatives,
            identifier_columns=["SKU"],
            weights=weights,
            directions=MCA_DIRECTIONS,
        )

        self.assertEqual(result.iloc[0]["SKU"], "A")
        self.assertEqual(result.iloc[0]["Priority Rank"], 1)
        self.assertTrue(result["SKU Priority Score"].between(0, 1).all())

    def test_weights_must_sum_to_one(self) -> None:
        alternatives = pd.DataFrame(
            {
                "SKU": ["A"],
                **{criterion: [1] for criterion in MCA_CRITERIA},
            }
        )
        weights = {criterion: 0.1 for criterion in MCA_CRITERIA}
        directions = {criterion: "benefit" for criterion in MCA_CRITERIA}
        with self.assertRaisesRegex(ValueError, "sum to 1.00"):
            calculate_mca_scores(
                alternatives,
                identifier_columns=["SKU"],
                weights=weights,
                directions=directions,
            )


if __name__ == "__main__":
    unittest.main()
