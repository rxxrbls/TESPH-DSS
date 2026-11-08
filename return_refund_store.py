"""Transactional review snapshots and append-only dispute audit.

Call refresh_batch for every accepted batch, even identical uploads. Passing no
new request snapshot reviews existing evidence. Partial snapshots upsert request
items and never delete an absent dispute. Calculation failures roll back.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from uuid import uuid4

import pandas as pd

from three_criterion_mca import POLICY_VERSION, REQUIRED, fingerprint, validate_snapshot


def _read(connection, key, fallback):
    row = connection.execute("SELECT payload FROM state WHERE name=?", (key,)).fetchone()
    return json.loads(row[0]) if row else fallback


def _write(connection, key, value):
    connection.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value, default=str)))


def refresh_batch(path, *, batch_type, calculate, snapshot=None, coverage=None):
    """Atomically publish review, all derived tables and audit after calculation.

    calculate(snapshot, coverage_dict) must return a dict of DataFrames containing
    return_request_review and the complete dependent results for this batch.
    """
    if batch_type not in {"sales", "stock", "return_refund"}:
        raise ValueError("Unsupported batch type")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS state(name TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS audit(event_id INTEGER PRIMARY KEY,run_id TEXT,payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS snapshots(fingerprint TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        previous = pd.DataFrame(_read(connection, "snapshot", []))
        if previous.empty:
            previous = pd.DataFrame(columns=REQUIRED)
        current = previous
        if snapshot is not None:
            incoming = validate_snapshot(snapshot)
            # Replace item evidence only where explicitly present in this batch.
            incoming_keys = set(zip(incoming["Return ID"], incoming["product_key"]))
            keep = [(r, p) not in incoming_keys for r, p in zip(previous["Return ID"], previous["product_key"])]
            current = pd.concat([previous.loc[keep], incoming], ignore_index=True)
        policy = asdict(coverage) if coverage is not None else _read(connection, "coverage", None)
        if policy is None:
            raise ValueError("Explicit assessment coverage required")
        results = calculate(current.copy(), policy)
        review = results["return_request_review"]
        old_review = {(x["Return ID"], x["product_key"]): x for x in _read(connection, "review", [])}
        run_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        source_hash = fingerprint(current)
        connection.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?)",
                           (source_hash, json.dumps(current.to_dict("records"), default=str)))
        for row in review.to_dict("records"):
            before = old_review.get((row["Return ID"], row["product_key"]), {})
            event = {
                "batch_type": batch_type, "reviewed_at_utc": now,
                "Return ID": row["Return ID"], "product_key": row["product_key"], "SKU": row.get("SKU"),
                "previous_source_status": before.get("Return / Refund Status"),
                "current_source_status": row["Return / Refund Status"],
                "previous_decision": before.get("Review Decision"), "current_decision": row["Review Decision"],
                "reason": row["Review Reason"], "source_fingerprint": source_hash,
                "policy_version": POLICY_VERSION, "recomputation_outcome": "complete",
                "coverage": policy,
                "export_date_start": policy["export_start"], "export_date_end": policy["export_end"],
                "snapshot_age_days": (pd.Timestamp(now).tz_localize(None).normalize() - pd.Timestamp(policy["export_end"])).days,
            }
            connection.execute("INSERT INTO audit(run_id,payload) VALUES (?,?)", (run_id, json.dumps(event, default=str)))
        _write(connection, "snapshot", current.to_dict("records"))
        _write(connection, "coverage", policy)
        _write(connection, "review", review.to_dict("records"))
        # JSON table schemas preserve empty output columns and numeric precision.
        _write(connection, "outputs", {name: frame.to_json(orient="table", double_precision=15)
                                      for name, frame in results.items()})
        _write(connection, "last_run", {"run_id": run_id, "reviewed_at_utc": now, "source_fingerprint": source_hash})
        _write(connection, "review_state", "complete")
        return results


def invalidate_outputs(path):
    """An accepted sales batch makes previous stock-dependent results stale."""
    with closing(sqlite3.connect(path, timeout=30)) as connection, connection:
        _write(connection, "outputs", {})
        _write(connection, "review_state", "pending sales refresh")


def load_evidence(path):
    if not Path(path).exists():
        return None
    with closing(sqlite3.connect(path)) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='state'").fetchone():
            return None
        policy = _read(connection, "coverage", None)
        if policy is None:
            return None
        return pd.DataFrame(_read(connection, "snapshot", []), columns=None), policy


def load_persisted_outputs(path: str | Path) -> dict[str, pd.DataFrame] | None:
    """Load cached prescriptive and audit outputs from SQLite state table if present."""
    if not Path(path).exists():
        return None
    with closing(sqlite3.connect(path)) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='state'").fetchone():
            return None
        raw_outputs = _read(connection, "outputs", None)
        if not raw_outputs or not isinstance(raw_outputs, dict):
            return None
        outputs: dict[str, pd.DataFrame] = {}
        for name, json_str in raw_outputs.items():
            if json_str:
                try:
                    outputs[name] = pd.read_json(io.StringIO(json_str), orient="table")
                except Exception:
                    pass
        return outputs if outputs else None

