import pytest
import pandas as pd
from analytics.data_loader import AnalyticsDataLoader
from etl_config import FINAL_SCHEMAS


def _write_valid_table(tmp_path, table_name):
    frame = pd.DataFrame([{column: "value" for column in FINAL_SCHEMAS[table_name]}])
    frame.to_csv(tmp_path / f"{table_name}.csv", index=False)
    return frame

def test_load_valid_csv(tmp_path):
    expected = _write_valid_table(tmp_path, "prepared_transactions")
    
    loader = AnalyticsDataLoader(output_dir=str(tmp_path))
    loaded_df = loader.load_prepared_transactions()
    
    assert len(loaded_df) == len(expected)
    assert list(loaded_df.columns) == list(expected.columns)

def test_missing_file(tmp_path):
    loader = AnalyticsDataLoader(output_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        loader.load_prepared_transactions()

def test_load_fact_sales(tmp_path):
    expected = _write_valid_table(tmp_path, "fact_sales")
    
    loader = AnalyticsDataLoader(output_dir=str(tmp_path))
    loaded_df = loader.load_fact_sales()
    
    assert len(loaded_df) == len(expected)
    assert list(loaded_df.columns) == list(expected.columns)

def test_empty_file(tmp_path):
    file_path = tmp_path / "fact_sales.csv"
    file_path.write_text("")
    
    loader = AnalyticsDataLoader(output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="Invalid fact_sales schema"):
        loader.load_fact_sales()

