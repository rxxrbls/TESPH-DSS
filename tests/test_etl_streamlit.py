import sqlite3

import pandas as pd

from etl_config import SOURCE_COLUMNS
from etl import transform_transactions
from etl_streamlit import run_etl_from_upload
from final_etl_handoff import build_star_schema_tables
from star_schema_db import LOAD_ORDER, PRIMARY_KEYS


def _upload_bytes() -> bytes:
    row = {column: "" for column in SOURCE_COLUMNS}
    row.update({
        "Order ID": "TEST-ORDER-1",
        "Order Status": "Completed",
        "Product Name": "Test Widget",
        "Variation Name": "Blue",
        "Parent SKU Reference No.": "PARENT-1",
        "SKU Reference No.": "SKU-1",
        "Quantity": 2,
        "Returned quantity": 0,
        "Original Price": 100.0,
        "Deal Price": 90.0,
        "Order Creation Date": "2026-01-15 10:00:00",
    })
    return pd.DataFrame([row]).to_csv(index=False).encode("utf-8")


def test_etl_streamlit_persists_returned_etlresult_to_isolated_database(tmp_path):
    """The upload's returned ETLResult and its isolated SQLite snapshot agree."""
    db_path = tmp_path / "streamlit_upload.db"
    raw = pd.read_csv(pd.io.common.BytesIO(_upload_bytes()))
    raw["source_file"] = "historical.csv"
    raw["source_folder"] = "historical"
    baseline_path = tmp_path / "prepared_transactions.csv"
    build_star_schema_tables(transform_transactions(raw))["prepared_transactions"].to_csv(
        baseline_path, index=False, encoding="utf-8-sig"
    )
    steps_called = []

    def on_step(index, name, msg):
        steps_called.append((index, name))

    result = run_etl_from_upload(
        _upload_bytes(), "test_upload.csv", on_step=on_step, db_path=db_path,
        baseline_path=baseline_path,
    )

    assert result.success is True, f"ETL failed: {result.error_message}"
    assert result.source_filename == "test_upload.csv"
    assert result.validation_report.is_valid is True
    # The Load step emits sub-step notifications (reading DB, reconciling,
    # building schema, persisting) so the total call count is > 5.  Verify
    # that every step index 0-4 fires at least once and the overall count is
    # at least 5 (one per canonical ETL step).
    step_indices = {index for index, _name in steps_called}
    assert step_indices == {0, 1, 2, 3, 4}, f"Not all step indices fired: {step_indices}"
    assert len(steps_called) >= 5, f"Expected at least 5 on_step calls, got {len(steps_called)}"
    assert isinstance(result.prepared_transactions, pd.DataFrame)
    assert len(result.prepared_transactions) > 0

    with sqlite3.connect(db_path) as conn:
        for table_name in LOAD_ORDER:
            assert table_name in result.star_schema
            assert isinstance(result.star_schema[table_name], pd.DataFrame)
            assert len(result.star_schema[table_name]) > 0
            persisted_count = conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            assert persisted_count == len(result.star_schema[table_name])

            key = PRIMARY_KEYS[table_name]
            persisted_keys = [str(row[0]) for row in conn.execute(
                f'SELECT "{key}" FROM "{table_name}" ORDER BY "{key}"'
            )]
            result_keys = sorted(result.star_schema[table_name][key].astype(str).tolist())
            assert persisted_keys == result_keys
