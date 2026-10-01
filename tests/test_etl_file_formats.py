"""Test ETL pipeline handles multiple CSV and XLSX input variants."""
import pytest
import tempfile
import pandas as pd
from pathlib import Path
from etl import extract_file, validate_required_columns

@pytest.fixture
def minimal_df():
    """Minimal valid Shopee-like DataFrame."""
    return pd.DataFrame({
        "Order ID": ["ORD001", "ORD002", "ORD003"],
        "Product Name": ["Widget A", "Widget B", "Widget C"],
        "Variation Name": ["Small", "Medium", "Large"],
        "Quantity": [1, 2, 3],
        "Order Creation Date": ["2025-01-01", "2025-01-02", "2025-01-03"],
        "Original Price": [100.0, 200.0, 150.0],
        "Deal Price": [90.0, 180.0, 135.0],
    })

class TestCSVEncodings:
    def test_utf8_csv(self, minimal_df, tmp_path):
        """Standard UTF-8 CSV is extracted correctly."""
        path = tmp_path / "test.csv"
        minimal_df.to_csv(path, index=False, encoding="utf-8")
        result = extract_file(path)
        assert len(result) == len(minimal_df)

    def test_utf8_bom_csv(self, minimal_df, tmp_path):
        """UTF-8 with BOM (common from Excel) is handled."""
        path = tmp_path / "test.csv"
        minimal_df.to_csv(path, index=False, encoding="utf-8-sig")
        result = extract_file(path)
        assert len(result) == len(minimal_df)

class TestCSVStructure:
    def test_csv_with_extra_columns(self, minimal_df, tmp_path):
        """Extra columns beyond expected schema are preserved."""
        minimal_df["Extra Column"] = "value"
        path = tmp_path / "test.csv"
        minimal_df.to_csv(path, index=False)
        result = extract_file(path)
        assert "Extra Column" in result.columns

    def test_empty_csv_raises(self, tmp_path):
        """Empty CSV file raises an appropriate error."""
        path = tmp_path / "empty.csv"
        path.write_text("")
        with pytest.raises(Exception):
            extract_file(path)

    def test_headers_only_csv(self, tmp_path):
        """CSV with headers but no data rows."""
        path = tmp_path / "headers.csv"
        path.write_text("Order ID,Product Name,Quantity\n")
        with pytest.raises(ValueError, match="no data rows"):
            extract_file(path)

class TestCSVValidation:
    def test_missing_order_id_column(self, minimal_df, tmp_path):
        """CSV missing 'Order ID' is detected by validate_required_columns."""
        df = minimal_df.drop(columns=["Order ID"])
        path = tmp_path / "test.csv"
        df.to_csv(path, index=False)
        result = extract_file(path)
        with pytest.raises(ValueError):
            validate_required_columns(result)

    def test_missing_quantity_column(self, minimal_df, tmp_path):
        """CSV missing 'Quantity' is detected."""
        df = minimal_df.drop(columns=["Quantity"])
        path = tmp_path / "test.csv"
        df.to_csv(path, index=False)
        result = extract_file(path)
        with pytest.raises(ValueError):
            validate_required_columns(result)

    def test_all_required_columns_present(self, minimal_df, tmp_path):
        """Valid CSV passes column validation."""
        path = tmp_path / "test.csv"
        minimal_df.to_csv(path, index=False)
        result = extract_file(path)
        mapping = validate_required_columns(result)
        assert "Order ID" in mapping.values() or "Order ID" in mapping

class TestCSVEdgeCases:
    def test_single_row_csv(self, tmp_path):
        """CSV with only one data row."""
        df = pd.DataFrame({"Order ID": ["ORD001"], "Product Name": ["X"],
                           "Quantity": [1], "Order Creation Date": ["2025-01-01"]})
        path = tmp_path / "test.csv"
        df.to_csv(path, index=False)
        result = extract_file(path)
        assert len(result) == 1

    def test_csv_with_unicode_product_names(self, tmp_path):
        """Product names with Unicode characters are preserved."""
        df = pd.DataFrame({"Order ID": ["ORD001"], "Product Name": ["Ñoño Café ™"],
                           "Quantity": [1], "Order Creation Date": ["2025-01-01"]})
        path = tmp_path / "test.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        result = extract_file(path)
        assert result["Product Name"].iloc[0] == "Ñoño Café ™"

class TestXLSXInputs:
    def test_single_sheet_xlsx(self, minimal_df, tmp_path):
        """XLSX with a single unnamed sheet is read correctly."""
        path = tmp_path / "test.xlsx"
        minimal_df.to_excel(path, index=False, engine="openpyxl")
        result = extract_file(path)
        assert len(result) == len(minimal_df)

    def test_orders_sheet_xlsx(self, minimal_df, tmp_path):
        """XLSX with an 'orders' sheet uses that sheet."""
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="metadata", index=False)
            minimal_df.to_excel(writer, sheet_name="orders", index=False)
        result = extract_file(path)
        assert len(result) == len(minimal_df)
        assert "Order ID" in result.columns

    def test_first_sheet_fallback(self, minimal_df, tmp_path):
        """XLSX without 'orders' sheet falls back to first sheet."""
        path = tmp_path / "test.xlsx"
        minimal_df.to_excel(path, index=False, sheet_name="data", engine="openpyxl")
        result = extract_file(path)
        assert len(result) == len(minimal_df)

    def test_empty_xlsx_raises(self, tmp_path):
        """Empty XLSX workbook raises ValueError."""
        path = tmp_path / "empty.xlsx"
        pd.DataFrame().to_excel(path, index=False, engine="openpyxl")
        with pytest.raises(ValueError, match="no data rows"):
            extract_file(path)

    def test_xlsx_missing_required_columns(self, minimal_df, tmp_path):
        """XLSX missing required columns is detected."""
        df = minimal_df.drop(columns=["Order ID"])
        path = tmp_path / "test.xlsx"
        df.to_excel(path, index=False, engine="openpyxl")
        result = extract_file(path)
        with pytest.raises(ValueError):
            validate_required_columns(result)

    def test_xlsx_with_extra_columns(self, minimal_df, tmp_path):
        """Extra columns in XLSX are preserved."""
        minimal_df["Custom Field"] = "custom"
        path = tmp_path / "test.xlsx"
        minimal_df.to_excel(path, index=False, engine="openpyxl")
        result = extract_file(path)
        assert "Custom Field" in result.columns
