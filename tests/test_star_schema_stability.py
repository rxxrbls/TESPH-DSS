"""Confirm Star Schema output structure and key integrity remain stable."""
import pytest
import pandas as pd
from etl import validate_final_schema, product_key
from etl_config import FINAL_SCHEMAS

class TestFrozenSchemas:
    """Every table's column set must match FINAL_SCHEMAS exactly."""

    @pytest.mark.parametrize("table_name", list(FINAL_SCHEMAS.keys()))
    def test_schema_columns_defined(self, table_name):
        """Each table has a non-empty frozen schema."""
        schema = FINAL_SCHEMAS[table_name]
        assert len(schema) > 0, f"{table_name} has empty schema"
        assert all(isinstance(col, str) for col in schema)

    def test_fact_sales_has_all_foreign_keys(self):
        """fact_sales schema includes all dimension foreign keys."""
        schema = FINAL_SCHEMAS["fact_sales"]
        assert "Order ID" in schema
        assert "product_key" in schema
        assert "date_key" in schema
        assert "shipping_key" in schema
        assert "payment_key" in schema

    def test_fact_sales_has_primary_key(self):
        """fact_sales schema includes sales_line_key."""
        assert "sales_line_key" in FINAL_SCHEMAS["fact_sales"]

    def test_dim_product_has_primary_key(self):
        assert "product_key" in FINAL_SCHEMAS["dim_product"]

    def test_dim_date_has_primary_key(self):
        assert "date_key" in FINAL_SCHEMAS["dim_date"]

    def test_dim_order_has_primary_key(self):
        assert "Order ID" in FINAL_SCHEMAS["dim_order"]

    def test_dim_shipping_has_primary_key(self):
        assert "shipping_key" in FINAL_SCHEMAS["dim_shipping"]

    def test_dim_payment_has_primary_key(self):
        assert "payment_key" in FINAL_SCHEMAS["dim_payment"]

    def test_prepared_transactions_column_count(self):
        """prepared_transactions has the expected 76 columns."""
        assert len(FINAL_SCHEMAS["prepared_transactions"]) == 76

class TestKeyDeterminism:
    """Key generation must be deterministic and reproducible."""

    def test_product_key_deterministic(self):
        """Same inputs always produce the same product_key."""
        key1 = product_key("Widget A", "Small")
        key2 = product_key("Widget A", "Small")
        assert key1 == key2

    def test_product_key_prefix(self):
        """Product keys start with 'prd_' prefix."""
        key = product_key("Test Product", "Variant")
        assert key.startswith("prd_")

    def test_product_key_length(self):
        """Product keys have consistent length."""
        key = product_key("Any Product", "Any Variant")
        assert len(key) > 10  # prd_ + hash chars

    def test_different_inputs_different_keys(self):
        """Different product/variation combinations produce unique keys."""
        keys = {
            product_key("A", "X"),
            product_key("A", "Y"),
            product_key("B", "X"),
            product_key("B", "Y"),
        }
        assert len(keys) == 4

    def test_product_key_case_insensitive_standardization(self):
        """Product key standardization is applied consistently."""
        from etl import standardize_product_value
        # product_key expects standardized inputs
        p1 = standardize_product_value("  Widget A  ")
        p2 = standardize_product_value("Widget A")
        key1 = product_key(p1, "small")
        key2 = product_key(p2, "small")
        # After standardization, trimmed names should match
        assert key1 == key2

class TestSchemaValidation:
    """validate_final_schema catches mismatches."""

    def test_valid_columns_pass(self):
        """Columns matching FINAL_SCHEMAS pass validation."""
        for table_name, columns in FINAL_SCHEMAS.items():
            validate_final_schema(columns, table_name)  # Should not raise

    def test_extra_column_fails(self):
        """An extra column causes validation to fail."""
        columns = FINAL_SCHEMAS["dim_date"] + ("extra_column",)
        with pytest.raises(ValueError):
            validate_final_schema(columns, "dim_date")

    def test_missing_column_fails(self):
        """A missing column causes validation to fail."""
        columns = FINAL_SCHEMAS["dim_date"][:-1]  # Remove last column
        with pytest.raises(ValueError):
            validate_final_schema(columns, "dim_date")

    def test_unknown_table_fails(self):
        """An unknown table name causes validation to fail."""
        with pytest.raises((ValueError, KeyError)):
            validate_final_schema(("col",), "nonexistent_table")
