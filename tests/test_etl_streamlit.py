import sqlite3

import pandas as pd

from etl_config import SOURCE_COLUMNS
from etl import transform_transactions
from etl_streamlit import run_etl_from_upload
from final_etl_handoff import build_star_schema_tables
from runtime_data_store import load_active_state
from star_schema_db import LOAD_ORDER, PRIMARY_KEYS


def _upload_bytes(
    order_id: str = "TEST-ORDER-1",
    *,
    order_date: str = "2026-01-15 10:00:00",
    quantity: object = 2,
) -> bytes:
    row = {column: "" for column in SOURCE_COLUMNS}
    row.update({
        "Order ID": order_id,
        "Order Status": "Completed",
        "Product Name": "Test Widget",
        "Variation Name": "Blue",
        "Parent SKU Reference No.": "PARENT-1",
        "SKU Reference No.": "SKU-1",
        "Quantity": quantity,
        "Returned quantity": 0,
        "Original Price": 100.0,
        "Deal Price": 90.0,
        "Order Creation Date": order_date,
    })
    return pd.DataFrame([row]).to_csv(index=False).encode("utf-8")


def _write_baseline(path, order_id: str = "BASELINE-1"):
    raw = pd.read_csv(pd.io.common.BytesIO(_upload_bytes(order_id)))
    raw["source_file"] = "historical.csv"
    raw["source_folder"] = "historical"
    prepared = build_star_schema_tables(transform_transactions(raw))["prepared_transactions"]
    prepared.to_csv(path, index=False, encoding="utf-8-sig")
    return prepared


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


def test_valid_transaction_upload_adds_one_row_to_active_history(tmp_path):
    db_path = tmp_path / "runtime.db"
    baseline_path = tmp_path / "prepared_transactions.csv"
    _write_baseline(baseline_path)

    result = run_etl_from_upload(
        _upload_bytes("UPLOAD-1"), "valid_month.csv",
        db_path=db_path, baseline_path=baseline_path,
    )

    assert result.success is True
    assert result.validation_report.row_count == 1
    assert result.reconciliation_summary["staged_rows"] == 1
    assert result.reconciliation_summary["new_rows"] == 1
    assert result.reconciliation_summary["active_rows"] == 2
    assert len(result.prepared_transactions) == 2
    assert set(result.prepared_transactions["Order ID"]) == {"BASELINE-1", "UPLOAD-1"}


def test_invalid_transaction_file_does_not_change_active_history(tmp_path):
    db_path = tmp_path / "runtime.db"
    baseline_path = tmp_path / "prepared_transactions.csv"
    _write_baseline(baseline_path)
    first = run_etl_from_upload(
        _upload_bytes("UPLOAD-1"), "valid.csv",
        db_path=db_path, baseline_path=baseline_path,
    )
    before = load_active_state(db_path=db_path, baseline_path=baseline_path)
    with sqlite3.connect(db_path) as conn:
        before_batches = pd.read_sql_query("SELECT * FROM ingestion_batches", conn)

    invalid_payload = pd.DataFrame({"not a Shopee column": ["bad"]}).to_csv(index=False).encode("utf-8")
    result = run_etl_from_upload(
        invalid_payload, "invalid.csv", db_path=db_path, baseline_path=baseline_path,
    )
    after = load_active_state(db_path=db_path, baseline_path=baseline_path)
    with sqlite3.connect(db_path) as conn:
        after_batches = pd.read_sql_query("SELECT * FROM ingestion_batches", conn)

    assert first.success is True
    assert result.success is False
    assert result.validation_report.row_count == 1
    assert len(before.transactions) == len(after.transactions) == 2
    pd.testing.assert_frame_equal(before.transactions, after.transactions, check_dtype=False)
    pd.testing.assert_frame_equal(before_batches, after_batches, check_dtype=False)


def test_malformed_transaction_values_are_rejected_before_persistence(tmp_path):
    db_path = tmp_path / "runtime.db"
    baseline_path = tmp_path / "prepared_transactions.csv"
    baseline = _write_baseline(baseline_path)

    result = run_etl_from_upload(
        _upload_bytes("MALFORMED-1", order_date="not-a-date", quantity="many"),
        "malformed.csv", db_path=db_path, baseline_path=baseline_path,
    )

    assert result.success is False
    assert result.validation_report.row_count == 1
    assert result.validation_report.data_type_issues == 2
    assert len(baseline) == 1
    assert not db_path.exists()
    assert result.prepared_transactions is None


def test_database_publication_failure_preserves_existing_active_history(monkeypatch, tmp_path):
    db_path = tmp_path / "runtime.db"
    baseline_path = tmp_path / "prepared_transactions.csv"
    _write_baseline(baseline_path)
    first = run_etl_from_upload(
        _upload_bytes("UPLOAD-1"), "valid.csv",
        db_path=db_path, baseline_path=baseline_path,
    )
    before = load_active_state(db_path=db_path, baseline_path=baseline_path)
    before_database = db_path.read_bytes()

    def fail_publication(*_args, **_kwargs):
        raise OSError("forced publication failure")

    monkeypatch.setattr("star_schema_db.load_runtime_snapshot", fail_publication)
    result = run_etl_from_upload(
        _upload_bytes("UPLOAD-2"), "valid_second.csv",
        db_path=db_path, baseline_path=baseline_path,
    )
    after = load_active_state(db_path=db_path, baseline_path=baseline_path)

    assert first.success is True
    assert result.success is False
    assert result.reconciliation_summary == {}
    assert result.validation_report.errors[0].startswith("Database persistence failed:")
    assert len(before.transactions) == len(after.transactions) == 2
    pd.testing.assert_frame_equal(before.transactions, after.transactions, check_dtype=False)
    assert db_path.read_bytes() == before_database
    assert "UPLOAD-2" not in set(after.transactions["Order ID"])
