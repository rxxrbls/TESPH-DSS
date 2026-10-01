import pandas as pd

from etl import load_final_table
from etl_config import FINAL_OUTPUT_DIR
from pathlib import Path

class AnalyticsDataLoader:
    def __init__(self, output_dir: str | Path = FINAL_OUTPUT_DIR):
        self.output_dir = Path(output_dir)

    def load_prepared_transactions(self) -> pd.DataFrame:
        """
        Loads the main prepared transactions dataset.
        """
        return load_final_table("prepared_transactions", self.output_dir)

    def load_fact_sales(self) -> pd.DataFrame:
        """
        Loads the fact_sales table.
        """
        return load_final_table("fact_sales", self.output_dir)
        
    def load_dim_product(self) -> pd.DataFrame:
        """
        Loads the dim_product table.
        """
        return load_final_table("dim_product", self.output_dir)

    def load_dim_order(self) -> pd.DataFrame:
        """
        Loads the dim_order table.
        """
        return load_final_table("dim_order", self.output_dir)
