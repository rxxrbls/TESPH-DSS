"""Shared ETL handoff reader; identifiers retain leading zeros."""

from pathlib import Path

import pandas as pd

from analytics_calculations import REQUIRED_SOURCE_COLUMNS


OUTPUT_DIR = Path(__file__).resolve().parent / "final_outputs"


def load_transactions(path: str | Path | None = None) -> pd.DataFrame:
    source = Path(path) if path is not None else OUTPUT_DIR / "prepared_transactions.csv"
    header = pd.read_csv(source, nrows=0).columns
    optional = ["Cancel reason", "Variation Name", "Service Fee"]
    columns = list(REQUIRED_SOURCE_COLUMNS) + [c for c in optional if c in header]
    return pd.read_csv(
        source, usecols=columns, low_memory=False,
        dtype={c: "string" for c in ("Order ID", "SKU Reference No.", "product_key")},
    )
