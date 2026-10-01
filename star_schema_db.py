"""Physical SQLite representation of the ETL star schema.

The database schema is derived from the same frozen table contracts used by
the ETL. This prevents an older, incompatible DDL from coexisting with the
current DataFrame output.
"""
from __future__ import annotations

import sqlite3
import os
from contextlib import closing
from pathlib import Path
import tempfile

import pandas as pd

from etl import validate_final_schema
from etl_config import FINAL_OUTPUT_DIR, FINAL_SCHEMAS, MEASURE_COLUMNS


DEFAULT_DB_PATH = FINAL_OUTPUT_DIR / "star_schema.db"
LOAD_ORDER = ["dim_product", "dim_date", "dim_order", "dim_shipping", "dim_payment", "fact_sales"]
PRIMARY_KEYS = {
    "dim_product": "product_key", "dim_date": "date_key", "dim_order": "Order ID",
    "dim_shipping": "shipping_key", "dim_payment": "payment_key", "fact_sales": "sales_line_key",
}
INTEGER_COLUMNS = {
    "date_key", "year", "month_number", "day", "Quantity", "Returned quantity",
    "Number of Items in Order", "order_year", "order_month",
}
BOOLEAN_COLUMNS = {"has_negative_financial_value", "is_completed", "is_cancelled", "is_returned", "has_order_attribute_conflict"}
INGESTION_BATCH_COLUMNS = [
    "batch_id", "source_filename", "uploaded_at", "staged_rows",
    "within_upload_duplicates", "existing_exact_rows", "new_rows",
    "possible_correction_rows", "ambiguous_identity_rows", "active_rows",
]
INGESTION_BATCH_COUNT_COLUMNS = {
    "staged_rows", "within_upload_duplicates", "existing_exact_rows", "new_rows",
    "possible_correction_rows", "ambiguous_identity_rows", "active_rows",
}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_type(column: str) -> str:
    if column in INTEGER_COLUMNS or column in BOOLEAN_COLUMNS:
        return "INTEGER"
    if column in MEASURE_COLUMNS:
        return "REAL"
    # SQLite has no native datetime. ISO datetime and source categorical data
    # are stored as TEXT without coercing legitimate source values.
    return "TEXT"


def _ddl(table_name: str) -> str:
    columns = [f"{_quote(column)} {_sqlite_type(column)}" for column in FINAL_SCHEMAS[table_name]]
    columns.append(f"PRIMARY KEY ({_quote(PRIMARY_KEYS[table_name])})")
    if table_name == "fact_sales":
        columns.extend([
            'FOREIGN KEY ("Order ID") REFERENCES dim_order("Order ID")',
            'FOREIGN KEY (product_key) REFERENCES dim_product(product_key)',
            'FOREIGN KEY (date_key) REFERENCES dim_date(date_key)',
            'FOREIGN KEY (shipping_key) REFERENCES dim_shipping(shipping_key)',
            'FOREIGN KEY (payment_key) REFERENCES dim_payment(payment_key)',
        ])
    return f"CREATE TABLE {_quote(table_name)} ({', '.join(columns)})"


def create_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create the frozen schema at ``db_path``.

    ``load_star_schema`` builds replacements at a temporary sibling path and
    only calls this helper for that unpublished database.  It is retained for
    callers that need a standalone empty schema.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for table_name in reversed(LOAD_ORDER):
            conn.execute(f"DROP TABLE IF EXISTS {_quote(table_name)}")
        for table_name in LOAD_ORDER:
            conn.execute(_ddl(table_name))


def _verify_table_contract(conn: sqlite3.Connection, table_name: str) -> None:
    actual = conn.execute(f"PRAGMA table_info({_quote(table_name)})").fetchall()
    columns = [row[1] for row in actual]
    expected = list(FINAL_SCHEMAS[table_name])
    if columns != expected:
        raise RuntimeError(f"SQLite schema mismatch for {table_name}: expected={expected}; actual={columns}")
    types = {row[1]: row[2].upper() for row in actual}
    mismatched = {column: (types[column], _sqlite_type(column)) for column in expected if types[column] != _sqlite_type(column)}
    if mismatched:
        raise RuntimeError(f"SQLite type mismatch for {table_name}: {mismatched}")


def load_table(conn: sqlite3.Connection, table_name: str, df: pd.DataFrame) -> int:
    """Insert one validated ETL table into its already-created table."""
    validate_final_schema(df.columns, table_name)
    _verify_table_contract(conn, table_name)
    df.to_sql(table_name, conn, if_exists="append", index=False)
    return len(df)


def _validate_persisted_database(
    db_path: Path, expected_counts: dict[str, int]
) -> None:
    """Validate a fully-written candidate before it becomes the live snapshot."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        for table_name, expected_count in expected_counts.items():
            _verify_table_contract(conn, table_name)
            actual_count = conn.execute(
                f"SELECT COUNT(*) FROM {_quote(table_name)}"
            ).fetchone()[0]
            if actual_count != expected_count:
                raise RuntimeError(
                    f"SQLite row-count mismatch for {table_name}: "
                    f"{actual_count} != {expected_count}"
                )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"SQLite foreign-key validation failed: {violations[:5]}")


def _temporary_database_path(db_path: Path) -> Path:
    """Return a closed temporary path on the destination filesystem."""
    descriptor, candidate = tempfile.mkstemp(
        prefix=f".{db_path.stem}.", suffix=".tmp", dir=db_path.parent
    )
    os.close(descriptor)
    return Path(candidate)


def load_star_schema(
    star_schema: dict[str, pd.DataFrame],
    prepared_transactions: pd.DataFrame | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, int]:
    """Create, load, and verify all star tables atomically.

    ``prepared_transactions`` is a session handoff, rather than an extra
    physical table, and is retained only for backwards-compatible callers.
    """
    missing = [table for table in LOAD_ORDER if table not in star_schema]
    if missing:
        raise ValueError("Star schema is missing required table(s): " + ", ".join(missing))
    for table_name in LOAD_ORDER:
        validate_final_schema(star_schema[table_name].columns, table_name)
    destination = Path(db_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = _temporary_database_path(destination)
    counts: dict[str, int] = {}
    try:
        # Never modify the published database while loading.  The temporary
        # database is in the same directory so os.replace is an atomic swap.
        create_database(candidate)
        with closing(sqlite3.connect(candidate)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for table_name in LOAD_ORDER:
                counts[table_name] = load_table(conn, table_name, star_schema[table_name])
        _validate_persisted_database(candidate, counts)
        os.replace(candidate, destination)
    except Exception:
        candidate.unlink(missing_ok=True)
        raise
    return counts


def load_runtime_snapshot(
    star_schema: dict[str, pd.DataFrame],
    prepared_transactions: pd.DataFrame,
    ingestion_batches: pd.DataFrame,
    metadata: dict[str, str],
    db_path: Path,
) -> dict[str, int]:
    """Atomically publish one reconciled local DSS snapshot.

    The runtime database deliberately keeps the active denormalized handoff
    beside its materialized Star Schema.  It is distinct from the immutable
    CSV/XLSX handoff under ``final_outputs``.  A candidate database is fully
    built and verified before replacement, so an upload failure cannot leave a
    partial active dataset visible to Streamlit.
    """
    validate_final_schema(prepared_transactions.columns, "prepared_transactions")
    missing = [table for table in LOAD_ORDER if table not in star_schema]
    if missing:
        raise ValueError("Star schema is missing required table(s): " + ", ".join(missing))
    for table_name in LOAD_ORDER:
        validate_final_schema(star_schema[table_name].columns, table_name)

    if list(ingestion_batches.columns) != INGESTION_BATCH_COLUMNS:
        raise ValueError("Invalid ingestion batch audit schema")

    destination = Path(db_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = _temporary_database_path(destination)
    counts: dict[str, int] = {}
    try:
        create_database(candidate)
        with closing(sqlite3.connect(candidate)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for table_name in LOAD_ORDER:
                counts[table_name] = load_table(conn, table_name, star_schema[table_name])

            prepared_columns = [
                f"{_quote(column)} {_sqlite_type(column)}"
                for column in FINAL_SCHEMAS["prepared_transactions"]
            ]
            conn.execute(
                f"CREATE TABLE prepared_transactions ({', '.join(prepared_columns)})"
            )
            prepared_transactions.to_sql(
                "prepared_transactions", conn, if_exists="append", index=False
            )
            conn.execute(
                "CREATE TABLE ingestion_batches ("
                "batch_id TEXT PRIMARY KEY, source_filename TEXT NOT NULL, "
                "uploaded_at TEXT NOT NULL, staged_rows INTEGER NOT NULL, "
                "within_upload_duplicates INTEGER NOT NULL, existing_exact_rows INTEGER NOT NULL, "
                "new_rows INTEGER NOT NULL, possible_correction_rows INTEGER NOT NULL, "
                "ambiguous_identity_rows INTEGER NOT NULL, active_rows INTEGER NOT NULL)"
            )
            ingestion_batches.to_sql(
                "ingestion_batches", conn, if_exists="append", index=False
            )
            conn.execute("CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.executemany(
                "INSERT INTO runtime_metadata(key, value) VALUES (?, ?)",
                sorted((str(key), str(value)) for key, value in metadata.items()),
            )

        _validate_persisted_database(candidate, counts)
        with closing(sqlite3.connect(candidate)) as conn:
            prepared_count = conn.execute("SELECT COUNT(*) FROM prepared_transactions").fetchone()[0]
            if prepared_count != len(prepared_transactions):
                raise RuntimeError(
                    "SQLite prepared transaction row-count mismatch: "
                    f"{prepared_count} != {len(prepared_transactions)}"
                )
            columns = [row[1] for row in conn.execute("PRAGMA table_info(prepared_transactions)")]
            if columns != list(FINAL_SCHEMAS["prepared_transactions"]):
                raise RuntimeError("SQLite prepared transaction schema mismatch")
        os.replace(candidate, destination)
    except Exception:
        candidate.unlink(missing_ok=True)
        raise
    return counts


def record_ingestion_batch(
    ingestion_batch: pd.DataFrame,
    *,
    expected_dataset_id: str,
    db_path: Path,
) -> bool:
    """Atomically record one content batch without replacing the runtime snapshot.

    ``batch_id`` is content-derived, so retries are idempotent and retain the
    first audit row. The active dataset ID is checked under the same write lock
    to avoid attaching the audit row to a snapshot that changed after reconcile.
    """
    if list(ingestion_batch.columns) != INGESTION_BATCH_COLUMNS or len(ingestion_batch) != 1:
        raise ValueError("Expected exactly one row with the ingestion batch audit schema")

    destination = Path(db_path)
    if not destination.is_file():
        raise FileNotFoundError(f"Runtime snapshot not found: {destination}")

    row = ingestion_batch.iloc[0]
    values = tuple(
        int(row[column]) if column in INGESTION_BATCH_COUNT_COLUMNS else str(row[column])
        for column in INGESTION_BATCH_COLUMNS
    )
    quoted_columns = ", ".join(_quote(column) for column in INGESTION_BATCH_COLUMNS)
    placeholders = ", ".join("?" for _ in INGESTION_BATCH_COLUMNS)

    with closing(sqlite3.connect(destination, timeout=30)) as conn:
        operation = "BEGIN IMMEDIATE"
        try:
            conn.execute("BEGIN IMMEDIATE")
            operation = "inspect runtime audit schema"
            tables = {
                record[0]
                for record in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"ingestion_batches", "runtime_metadata"}.issubset(tables):
                raise RuntimeError("Runtime database is missing audit or metadata tables")
            columns = [
                record[1]
                for record in conn.execute("PRAGMA table_info(ingestion_batches)")
            ]
            if columns != INGESTION_BATCH_COLUMNS:
                raise RuntimeError("Runtime database has an invalid ingestion batch audit schema")

            operation = "verify active dataset ID"
            current_dataset = conn.execute(
                "SELECT value FROM runtime_metadata WHERE key = 'dataset_id'"
            ).fetchone()
            if current_dataset is None or current_dataset[0] != expected_dataset_id:
                raise RuntimeError("Runtime dataset changed before the ingestion audit could be recorded")

            operation = "INSERT OR IGNORE ingestion batch"
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO ingestion_batches ({quoted_columns}) "
                f"VALUES ({placeholders})",
                values,
            )
            inserted = cursor.rowcount == 1
            operation = "COMMIT ingestion batch audit"
            conn.commit()
            return inserted
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(f"{operation} failed: {exc}") from exc


def get_table_counts(db_path: Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """Return row counts for the ETL star tables only."""
    if not Path(db_path).exists():
        return {}
    with closing(sqlite3.connect(db_path)) as conn:
        return {
            table_name: conn.execute(f"SELECT COUNT(*) FROM {_quote(table_name)}").fetchone()[0]
            for table_name in LOAD_ORDER
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        }


def read_runtime_snapshot(db_path: Path = DEFAULT_DB_PATH) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Load the published runtime snapshot without rebuilding it."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Runtime snapshot not found: {path}")

    with closing(sqlite3.connect(path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [table_name for table_name in LOAD_ORDER if table_name not in tables]
        if missing:
            raise ValueError(f"Runtime database is missing star tables: {missing}")

        star_schema = {
            table_name: pd.read_sql_query(f"SELECT * FROM {_quote(table_name)}", conn)
            for table_name in LOAD_ORDER
        }
        prepared = pd.read_sql_query("SELECT * FROM prepared_transactions", conn)
        for column in sorted(BOOLEAN_COLUMNS):
            if column not in prepared.columns:
                continue
            values = prepared[column].astype("string").str.strip().str.casefold()
            valid = values.isin(("0", "1", "false", "true"))
            if not valid.all():
                raise RuntimeError(f"Runtime database has invalid boolean values in {column}")
            prepared[column] = values.isin(("1", "true"))

    for table_name in LOAD_ORDER:
        validate_final_schema(star_schema[table_name].columns, table_name)
    validate_final_schema(prepared.columns, "prepared_transactions")
    return star_schema, prepared
