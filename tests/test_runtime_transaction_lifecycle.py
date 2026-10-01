"""Focused tests for immutable-baseline runtime transaction reconciliation."""
from __future__ import annotations

from hashlib import sha256
from contextlib import closing
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread

import pandas as pd
import pytest

from etl import extract_file, load_prepared_transactions, transform_transactions
from etl_config import SOURCE_COLUMNS
from final_etl_handoff import build_star_schema_tables
from runtime_data_store import (
    RuntimeState,
    load_active_state,
    payload_fingerprints,
    publish_validated_upload,
    reconcile_validated_upload,
    runtime_database_lock,
)
from star_schema_db import read_runtime_snapshot, record_ingestion_batch
import utils.state as app_state


def _raw_row(order_id: str, *, product: str = "Widget", quantity: int = 1) -> dict:
    row = {column: "" for column in SOURCE_COLUMNS}
    row.update({
        "Order ID": order_id,
        "Order Status": "Completed",
        "Product Name": product,
        "Variation Name": "Blue",
        "Parent SKU Reference No.": f"P-{product}",
        "SKU Reference No.": f"SKU-{product}",
        "Quantity": quantity,
        "Returned quantity": 0,
        "Original Price": 100,
        "Deal Price": 90,
        "Total Buyer Payment": quantity * 90,
        "Grand Total": quantity * 90,
        "Order Creation Date": "2026-01-15 10:00:00",
    })
    return row


def _prepared(rows: list[dict], filename: str = "source.csv") -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    raw["source_file"] = filename
    raw["source_folder"] = "uploaded"
    tables = build_star_schema_tables(transform_transactions(raw))
    return tables["prepared_transactions"]


def _baseline(tmp_path: Path, rows: list[dict]) -> tuple[Path, pd.DataFrame]:
    prepared = _prepared(rows, "historical.csv")
    path = tmp_path / "prepared_transactions.csv"
    prepared.to_csv(path, index=False, encoding="utf-8-sig")
    return path, prepared


def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _ingestion_batches(path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(path)
    try:
        return pd.read_sql_query(
            "SELECT * FROM ingestion_batches ORDER BY uploaded_at, batch_id", conn
        )
    finally:
        conn.close()


def test_runtime_database_lock_serializes_competing_uploads_and_releases(tmp_path):
    database = tmp_path / "runtime.db"
    first_lock = runtime_database_lock(database)
    second_lock = runtime_database_lock(database)
    attempting = Event()
    acquired = Event()
    errors = []

    def acquire_second_lock():
        attempting.set()
        try:
            with second_lock:
                acquired.set()
        except Exception as exc:
            errors.append(exc)

    with first_lock:
        worker = Thread(target=acquire_second_lock)
        worker.start()
        assert attempting.wait(1)
        assert acquired.wait(0.1) is False

    worker.join(timeout=2)
    assert not worker.is_alive()
    assert not errors
    assert acquired.is_set()

    with pytest.raises(RuntimeError, match="release check"):
        with runtime_database_lock(database):
            raise RuntimeError("release check")
    with runtime_database_lock(database, timeout=0.1):
        pass


def test_runtime_read_connection_closes_after_failure(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="seed.csv",
        db_path=database, baseline_path=baseline,
    )
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE prepared_transactions SET is_completed = 'invalid'")

    with pytest.raises(RuntimeError, match="invalid boolean values"):
        load_active_state(db_path=database, baseline_path=baseline)

    moved = tmp_path / "runtime-moved.db"
    database.replace(moved)
    moved.replace(database)


def test_audit_lock_contention_rolls_back_and_succeeds_on_retry(monkeypatch, tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="seed.csv",
        db_path=database, baseline_path=baseline,
    )
    active = load_active_state(db_path=database, baseline_path=baseline)
    repeated = reconcile_validated_upload(
        _prepared([_raw_row("O-1")]), active, source_filename="retry.csv"
    )
    batch_id = repeated.summary["batch_id"]
    audit_batch = repeated.batches.loc[repeated.batches["batch_id"].eq(batch_id)].iloc[[-1]]
    before = _ingestion_batches(database)
    holder = sqlite3.connect(database, timeout=0.05)
    holder.execute("BEGIN IMMEDIATE")

    import star_schema_db
    original_connect = sqlite3.connect

    def short_timeout_connect(path, **kwargs):
        kwargs["timeout"] = 0.05
        return original_connect(path, **kwargs)

    monkeypatch.setattr(star_schema_db.sqlite3, "connect", short_timeout_connect)
    with pytest.raises(RuntimeError, match="BEGIN IMMEDIATE failed: database is locked"):
        record_ingestion_batch(
            audit_batch, expected_dataset_id=active.dataset_id, db_path=database
        )
    assert len(_ingestion_batches(database)) == len(before)

    holder.rollback()
    holder.close()
    assert record_ingestion_batch(
        audit_batch, expected_dataset_id=active.dataset_id, db_path=database
    ) is True
    assert len(_ingestion_batches(database)) == len(before) + 1
    assert load_active_state(db_path=database, baseline_path=baseline).dataset_id == active.dataset_id
    with closing(sqlite3.connect(database)) as conn, conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_concurrent_duplicate_uploads_serialize_at_etl_entry_point(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="seed.csv",
        db_path=database, baseline_path=baseline,
    )
    payload = pd.DataFrame([_raw_row("O-1")]).to_csv(index=False).encode("utf-8")
    start = Barrier(2)

    def upload(filename):
        start.wait(timeout=5)
        return __import__("etl_streamlit", fromlist=["run_etl_from_upload"]).run_etl_from_upload(
            payload, filename, db_path=database, baseline_path=baseline
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(upload, ("duplicate-a.csv", "duplicate-b.csv")))

    assert all(result.success for result in results)
    assert all(result.reconciliation_summary["new_rows"] == 0 for result in results)
    assert all(result.dataset_id == load_active_state(db_path=database, baseline_path=baseline).dataset_id for result in results)
    assert len(_ingestion_batches(database)) == 2
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prepared_transactions").fetchone()[0] == 2
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_bootstrap_uses_immutable_baseline_and_first_publish_preserves_it(tmp_path):
    baseline, expected = _baseline(tmp_path, [_raw_row("O-1"), _raw_row("O-2", product="Other")])
    before = _checksum(baseline)
    state = load_active_state(db_path=tmp_path / "runtime.db", baseline_path=baseline)
    assert state.bootstrapped_from_baseline is True
    assert len(state.transactions) == len(expected)
    assert state.transactions["Order ID"].tolist() == expected["Order ID"].tolist()

    _, active, summary, _ = publish_validated_upload(
        _prepared([_raw_row("O-3", product="New")]), source_filename="new.csv",
        db_path=tmp_path / "runtime.db", baseline_path=baseline,
    )
    assert summary["new_rows"] == 1
    assert len(active) == 3
    assert _checksum(baseline) == before


def test_reupload_deduplicates_content_even_when_filename_changes(tmp_path):
    baseline, historical = _baseline(tmp_path, [_raw_row("O-1")])
    _, active, first, _ = publish_validated_upload(
        _prepared([_raw_row("O-1")], "renamed-export.xlsx"), source_filename="renamed-export.xlsx",
        db_path=tmp_path / "runtime.db", baseline_path=baseline,
    )
    assert first["existing_exact_rows"] == 1
    assert first["new_rows"] == 0
    assert len(active) == len(historical)

    _, active, second, _ = publish_validated_upload(
        _prepared([_raw_row("O-1")], "another-name.csv"), source_filename="another-name.csv",
        db_path=tmp_path / "runtime.db", baseline_path=baseline,
    )
    assert second["existing_exact_rows"] == 1
    assert second["new_rows"] == 0
    assert len(active) == len(historical)


def test_new_partial_and_sequential_uploads_accumulate_once(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    _, active, partial, _ = publish_validated_upload(
        _prepared([_raw_row("O-1"), _raw_row("O-2", product="Two")]), source_filename="partial.csv",
        db_path=database, baseline_path=baseline,
    )
    assert partial["existing_exact_rows"] == 1
    assert partial["new_rows"] == 1
    assert len(active) == 2

    _, active, next_batch, _ = publish_validated_upload(
        _prepared([_raw_row("O-3", product="Three")]), source_filename="later.csv",
        db_path=database, baseline_path=baseline,
    )
    assert next_batch["new_rows"] == 1
    assert set(active["Order ID"]) == {"O-1", "O-2", "O-3"}


def test_exact_duplicates_inside_staging_do_not_create_canonical_duplicates(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    _, active, summary, _ = publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two"), _raw_row("O-2", product="Two")]),
        source_filename="duplicate-rows.csv", db_path=tmp_path / "runtime.db", baseline_path=baseline,
    )
    assert summary["within_upload_duplicates"] == 1
    assert summary["new_rows"] == 1
    assert len(active) == 2


def test_changed_possible_identity_is_quarantined_not_silently_overwritten(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1", quantity=1)])
    _, active, summary, _ = publish_validated_upload(
        _prepared([_raw_row("O-1", quantity=2)]), source_filename="corrected.csv",
        db_path=tmp_path / "runtime.db", baseline_path=baseline,
    )
    assert summary["new_rows"] == 0
    assert summary["possible_correction_rows"] == 1
    assert active["Quantity"].tolist() == [1]


def test_failed_schema_does_not_replace_existing_runtime_snapshot(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="good.csv",
        db_path=database, baseline_path=baseline,
    )
    before = database.read_bytes()
    invalid = _prepared([_raw_row("O-3", product="Three")]).drop(columns="Order ID")
    with pytest.raises(ValueError):
        publish_validated_upload(
            invalid, source_filename="bad.csv", db_path=database, baseline_path=baseline,
        )
    assert database.read_bytes() == before
    assert len(load_active_state(db_path=database, baseline_path=baseline).transactions) == 2


def test_active_stars_and_prepared_transactions_share_one_snapshot(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    stars, active, _, dataset_id = publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="new.csv",
        db_path=database, baseline_path=baseline,
    )
    assert len(active) == len(stars["fact_sales"])
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prepared_transactions").fetchone()[0] == len(active)
        assert conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0] == len(stars["fact_sales"])
        assert dict(conn.execute("SELECT key, value FROM runtime_metadata"))["dataset_id"] == dataset_id
    reloaded = load_active_state(db_path=database, baseline_path=baseline).transactions
    assert all(str(reloaded[column].dtype) == "bool" for column in (
        "is_completed", "is_cancelled", "is_returned", "has_negative_financial_value",
    ))


def test_current_stock_session_state_is_isolated_from_active_transactions(monkeypatch, tmp_path):
    """Current stock is a separate snapshot; storing it cannot alter history."""
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    _, active, _, _ = publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="new.csv",
        db_path=tmp_path / "runtime.db", baseline_path=baseline,
    )
    values = {"prepared_transactions": active, "star_schema": {}}
    monkeypatch.setattr(app_state.st, "session_state", values)
    before = payload_fingerprints(active).tolist()
    app_state.set_inventory_results(
        pd.DataFrame({"SKU": ["CURRENT-1"], "Stock": [5]}),
        pd.DataFrame({"SKU": ["CURRENT-1"], "product_key": ["P1"]}),
        {"valid": True},
    )
    assert payload_fingerprints(values["prepared_transactions"]).tolist() == before
    assert values["inventory_data"].iloc[0]["Stock"] == 5


def test_real_historical_reupload_is_idempotent_against_governed_baseline():
    """Regression only: production reconciliation contains no August-specific rule."""
    baseline = load_prepared_transactions()
    raw = extract_file("raw_data/2022/Order.all.AUG2022.xlsx")
    raw["source_file"] = "test-renamed-upload.xlsx"
    raw["source_folder"] = "uploaded"
    staging = build_star_schema_tables(transform_transactions(raw))["prepared_transactions"]
    state = RuntimeState(
        transactions=baseline,
        batches=pd.DataFrame(columns=[
            "batch_id", "source_filename", "uploaded_at", "staged_rows",
            "within_upload_duplicates", "existing_exact_rows", "new_rows",
            "possible_correction_rows", "ambiguous_identity_rows", "active_rows",
        ]),
        dataset_id="baseline",
        bootstrapped_from_baseline=True,
    )
    result = reconcile_validated_upload(staging, state, source_filename="test-renamed-upload.xlsx")
    assert result.summary["staged_rows"] == len(staging)
    assert result.summary["existing_exact_rows"] == len(staging)
    assert result.summary["new_rows"] == 0
    assert result.summary["possible_correction_rows"] == 0
    assert len(result.transactions) == len(baseline)
    assert pd.to_datetime(result.transactions["order_date"]).min() == pd.Timestamp("2020-05-22")
    assert pd.to_datetime(result.transactions["order_date"]).max() == pd.Timestamp("2026-04-24")


def test_zero_new_row_upload_reuses_existing_runtime_outputs(monkeypatch, tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    _, _, _, dataset_id = publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="new.csv",
        db_path=database, baseline_path=baseline,
    )
    before_batches = _ingestion_batches(database)
    before_stars, before_prepared = read_runtime_snapshot(database)

    def fail_full_publication(*_args, **_kwargs):
        raise AssertionError("zero-new-row upload must not republish the runtime snapshot")

    monkeypatch.setattr("star_schema_db.load_runtime_snapshot", fail_full_publication)
    csv_payload = pd.DataFrame([_raw_row("O-1")]).to_csv(index=False, encoding="utf-8")
    result = __import__("etl_streamlit", fromlist=["run_etl_from_upload"]).run_etl_from_upload(
        csv_payload.encode("utf-8"), "renamed-same-export.csv", db_path=database, baseline_path=baseline,
    )

    assert result.success is True
    assert result.reused_existing_outputs is True
    assert result.reconciliation_summary["new_rows"] == 0
    assert result.dataset_id == dataset_id
    after_batches = _ingestion_batches(database)
    assert len(after_batches) == len(before_batches) + 1
    audit = after_batches.loc[after_batches["batch_id"].eq(result.reconciliation_summary["batch_id"])].iloc[0]
    assert audit["source_filename"] == "renamed-same-export.csv"
    assert int(audit["new_rows"]) == 0
    after_stars, after_prepared = read_runtime_snapshot(database)
    pd.testing.assert_frame_equal(before_prepared, after_prepared, check_dtype=False)
    for table_name in before_stars:
        pd.testing.assert_frame_equal(before_stars[table_name], after_stars[table_name], check_dtype=False)
    assert len(result.prepared_transactions) == len(load_active_state(db_path=database, baseline_path=baseline).transactions)

    for filename in ("renamed-same-export.csv", "third-name-same-export.csv"):
        repeated = __import__("etl_streamlit", fromlist=["run_etl_from_upload"]).run_etl_from_upload(
            csv_payload.encode("utf-8"), filename, db_path=database, baseline_path=baseline,
        )
        assert repeated.success is True
        assert repeated.reused_existing_outputs is True
        assert repeated.reconciliation_summary["new_rows"] == 0
        assert repeated.dataset_id == dataset_id
        assert len(_ingestion_batches(database)) == len(after_batches)


def test_invalid_upload_does_not_create_ingestion_audit(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="new.csv",
        db_path=database, baseline_path=baseline,
    )
    before = load_active_state(db_path=database, baseline_path=baseline)
    before_batches = _ingestion_batches(database)
    invalid = pd.DataFrame({"not a Shopee column": ["bad"]}).to_csv(index=False).encode("utf-8")

    result = __import__("etl_streamlit", fromlist=["run_etl_from_upload"]).run_etl_from_upload(
        invalid, "invalid.csv", db_path=database, baseline_path=baseline,
    )

    after = load_active_state(db_path=database, baseline_path=baseline)
    assert result.success is False
    assert result.reused_existing_outputs is False
    assert after.dataset_id == before.dataset_id
    pd.testing.assert_frame_equal(after.transactions, before.transactions, check_dtype=False)
    pd.testing.assert_frame_equal(_ingestion_batches(database), before_batches, check_dtype=False)


def test_zero_new_row_audit_failure_rolls_back_without_changing_authority(tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="new.csv",
        db_path=database, baseline_path=baseline,
    )
    before = load_active_state(db_path=database, baseline_path=baseline)
    before_batches = _ingestion_batches(database)
    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON ingestion_batches "
            "BEGIN SELECT RAISE(ABORT, 'forced audit failure'); END"
        )
        conn.commit()
    finally:
        conn.close()
    before_stars, before_prepared = read_runtime_snapshot(database)
    csv_payload = pd.DataFrame([_raw_row("O-1")]).to_csv(index=False, encoding="utf-8")

    result = __import__("etl_streamlit", fromlist=["run_etl_from_upload"]).run_etl_from_upload(
        csv_payload.encode("utf-8"), "same-export.csv", db_path=database, baseline_path=baseline,
    )

    after = load_active_state(db_path=database, baseline_path=baseline)
    after_stars, after_prepared = read_runtime_snapshot(database)
    assert result.success is False
    assert "forced audit failure" in result.error_message
    assert result.validation_report.step_results[2].success is True
    assert result.validation_report.step_results[4].success is False
    assert result.validation_report.errors[0].startswith("Database persistence failed:")
    assert result.dataset_id is None
    assert after.dataset_id == before.dataset_id
    pd.testing.assert_frame_equal(after.transactions, before.transactions, check_dtype=False)
    pd.testing.assert_frame_equal(_ingestion_batches(database), before_batches, check_dtype=False)
    pd.testing.assert_frame_equal(before_prepared, after_prepared, check_dtype=False)
    for table_name in before_stars:
        pd.testing.assert_frame_equal(before_stars[table_name], after_stars[table_name], check_dtype=False)
    conn = sqlite3.connect(database)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_partial_and_new_uploads_still_publish_full_runtime_snapshot(monkeypatch, tmp_path):
    baseline, _ = _baseline(tmp_path, [_raw_row("O-1")])
    database = tmp_path / "runtime.db"
    publish_validated_upload(
        _prepared([_raw_row("O-2", product="Two")]), source_filename="seed.csv",
        db_path=database, baseline_path=baseline,
    )
    original_id = load_active_state(db_path=database, baseline_path=baseline).dataset_id
    publication_calls = []
    import star_schema_db

    load_snapshot = star_schema_db.load_runtime_snapshot

    def count_publication(*args, **kwargs):
        publication_calls.append(True)
        return load_snapshot(*args, **kwargs)

    monkeypatch.setattr(star_schema_db, "load_runtime_snapshot", count_publication)
    orchestrator = __import__("etl_streamlit", fromlist=["run_etl_from_upload"])

    partial_csv = pd.DataFrame([_raw_row("O-1"), _raw_row("O-3", product="Three")]).to_csv(
        index=False, encoding="utf-8"
    )
    partial = orchestrator.run_etl_from_upload(
        partial_csv.encode("utf-8"), "partial.csv", db_path=database, baseline_path=baseline,
    )
    assert partial.success is True
    assert partial.reused_existing_outputs is False
    assert partial.reconciliation_summary["existing_exact_rows"] == 1
    assert partial.reconciliation_summary["new_rows"] == 1
    assert len(partial.prepared_transactions) == 3
    assert partial.dataset_id != original_id
    assert publication_calls == [True]

    new_csv = pd.DataFrame([_raw_row("O-4", product="Four")]).to_csv(
        index=False, encoding="utf-8"
    )
    new_upload = orchestrator.run_etl_from_upload(
        new_csv.encode("utf-8"), "new.csv", db_path=database, baseline_path=baseline,
    )
    assert new_upload.success is True
    assert new_upload.reused_existing_outputs is False
    assert new_upload.reconciliation_summary["new_rows"] == 1
    assert len(new_upload.prepared_transactions) == 4
    assert new_upload.dataset_id != partial.dataset_id
    assert publication_calls == [True, True]
