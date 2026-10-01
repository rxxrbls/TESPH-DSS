"""Validate that one successful ETL run is persisted to its SQLite snapshot.

The historical ``final_outputs/*.csv`` handoff is intentionally not used
here: it is independent of the most recent Streamlit upload.
"""
import sqlite3

import pandas as pd
import pytest

from etl_config import FINAL_SCHEMAS, SOURCE_COLUMNS
from etl import transform_transactions
from etl_streamlit import run_etl_from_upload
from final_etl_handoff import build_star_schema_tables
from star_schema_db import LOAD_ORDER, PRIMARY_KEYS, load_star_schema


def _upload_bytes() -> bytes:
    """Build the smallest complete Shopee-shaped export accepted by the ETL."""
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


@pytest.fixture
def successful_run(tmp_path):
    db_path = tmp_path / "latest_upload.db"
    raw = pd.read_csv(pd.io.common.BytesIO(_upload_bytes()))
    raw["source_file"] = "historical.csv"
    raw["source_folder"] = "historical"
    baseline_path = tmp_path / "prepared_transactions.csv"
    build_star_schema_tables(transform_transactions(raw))["prepared_transactions"].to_csv(
        baseline_path, index=False, encoding="utf-8-sig"
    )
    result = run_etl_from_upload(
        _upload_bytes(), "upload.csv", db_path=db_path, baseline_path=baseline_path
    )
    assert result.success, result.error_message
    return result, db_path


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")')]


def _assert_relevant_values_match(
    conn: sqlite3.Connection, table_name: str, expected: pd.DataFrame
) -> None:
    primary_key = PRIMARY_KEYS[table_name]
    columns = [primary_key]
    if table_name == "fact_sales":
        columns += ["Order ID", "product_key", "Quantity", "Deal Price"]
    elif table_name == "dim_product":
        columns += ["final_base_product_name", "SKU"]
    elif table_name == "dim_date":
        columns += ["full_date", "year", "month_number"]
    elif table_name == "dim_order":
        columns += ["Order Status", "Order Creation Date"]
    elif table_name == "dim_shipping":
        columns += ["Shipping Option", "Province"]
    elif table_name == "dim_payment":
        columns += ["Hot Listing", "Invoice type"]

    query_columns = ", ".join(f'"{column}"' for column in columns)
    actual = pd.read_sql_query(
        f'SELECT {query_columns} FROM "{table_name}" ORDER BY "{primary_key}"', conn
    )
    expected_values = expected[columns].sort_values(primary_key).reset_index(drop=True)
    if "full_date" in columns:
        actual["full_date"] = pd.to_datetime(actual["full_date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        expected_values["full_date"] = pd.to_datetime(expected_values["full_date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    actual = actual.astype("string").fillna("<NA>")
    expected_values = expected_values.astype("string").fillna("<NA>")
    pd.testing.assert_frame_equal(actual, expected_values, check_dtype=False)


@pytest.mark.parametrize("table_name", LOAD_ORDER)
def test_same_run_etlresult_is_persisted_to_sqlite(successful_run, table_name):
    """SQLite is reconciled to the ETLResult from this exact upload run."""
    result, db_path = successful_run
    with sqlite3.connect(db_path) as conn:
        assert _table_columns(conn, table_name) == list(FINAL_SCHEMAS[table_name])
        actual_count = conn.execute(
            f'SELECT COUNT(*) FROM "{table_name}"'
        ).fetchone()[0]
        assert actual_count == len(result.star_schema[table_name])
        _assert_relevant_values_match(conn, table_name, result.star_schema[table_name])


def test_failed_replacement_preserves_previous_valid_database(successful_run):
    """A failed candidate write cannot empty or partially replace the snapshot."""
    result, db_path = successful_run
    with sqlite3.connect(db_path) as conn:
        before_counts = {
            table_name: conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            for table_name in LOAD_ORDER
        }
        before_fact = conn.execute(
            'SELECT sales_line_key, product_key FROM fact_sales'
        ).fetchall()

    invalid_schema = {
        table_name: table.copy(deep=True)
        for table_name, table in result.star_schema.items()
    }
    invalid_schema["fact_sales"].loc[0, "product_key"] = "missing-product-key"

    with pytest.raises(pd.errors.DatabaseError, match="Execution failed"):
        load_star_schema(invalid_schema, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        after_counts = {
            table_name: conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            for table_name in LOAD_ORDER
        }
        after_fact = conn.execute(
            'SELECT sales_line_key, product_key FROM fact_sales'
        ).fetchall()
    assert after_counts == before_counts
    assert after_fact == before_fact
