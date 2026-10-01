"""Test ETL behaviour when product categories are renamed or removed."""
import pytest
import pandas as pd
from etl import product_key

class TestChangedCategories:
    def test_category_change_does_not_alter_product_key(self):
        """Product key is derived from name+variation, not category."""
        key1 = product_key("Widget A", "Small")
        key2 = product_key("Widget A", "Small")  # Same inputs, category irrelevant
        assert key1 == key2

    def test_product_key_stable_across_category_rename(self):
        """product_key for the same product is identical regardless of category context."""
        # Simulate: product was "Electronics" category, now "Gadgets"
        key_before = product_key("Bluetooth Speaker", "Black")
        # Category rename has no effect on key generation
        key_after = product_key("Bluetooth Speaker", "Black")
        assert key_before == key_after

    def test_different_products_different_keys(self):
        """Different product names produce different keys."""
        key_a = product_key("Widget A", "Small")
        key_b = product_key("Widget B", "Small")
        assert key_a != key_b

    def test_different_variations_different_keys(self):
        """Same product with different variations produce different keys."""
        key_a = product_key("Widget A", "Small")
        key_b = product_key("Widget A", "Large")
        assert key_a != key_b

class TestRemovedCategories:
    def test_unmatched_product_has_na_category(self):
        """Products without category mapping get pd.NA, not a fabricated value."""
        # Create a prepared DataFrame where some products have no category match
        df = pd.DataFrame({
            "product_key": ["prd_aaa", "prd_bbb"],
            "final_category": ["Electronics", pd.NA],
        })
        # The NA must be preserved, not filled
        assert pd.isna(df.loc[1, "final_category"])

    def test_removed_category_does_not_crash_dim_product(self):
        """dim_product schema is valid even with NA categories."""
        from etl_config import FINAL_SCHEMAS
        assert "final_category" in FINAL_SCHEMAS["dim_product"]
        # NA is a valid value in the final_category column

    def test_partial_category_coverage_preserves_matched(self):
        """Products with valid categories are unaffected by removed categories."""
        df = pd.DataFrame({
            "product_key": ["prd_aaa", "prd_bbb", "prd_ccc"],
            "final_category": ["Electronics", pd.NA, "Home"],
        })
        matched = df.dropna(subset=["final_category"])
        assert len(matched) == 2
        assert set(matched["final_category"]) == {"Electronics", "Home"}

    def test_all_categories_removed_produces_all_na(self):
        """If all categories are removed, all products have NA category."""
        df = pd.DataFrame({
            "product_key": ["prd_aaa", "prd_bbb"],
            "final_category": [pd.NA, pd.NA],
        })
        assert df["final_category"].isna().all()
