"""Local active transaction authority for the upload-driven DSS.

``final_outputs/prepared_transactions.csv`` is a governed, immutable baseline.
This module reads it only to bootstrap a local SQLite snapshot, then reconciles
validated upload staging data conservatively before atomically publishing the
next active snapshot.  It intentionally contains no Streamlit or forecasting
logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from contextlib import closing
from pathlib import Path
import sqlite3

import pandas as pd
from filelock import FileLock

from etl import load_prepared_transactions, validate_final_schema
from etl_config import (
    DATE_SOURCE_COLUMNS,
    FINAL_OUTPUT_DIR,
    FINAL_SCHEMAS,
    MEASURE_COLUMNS,
    RUNTIME_DB_PATH,
    STATUS_COLUMNS,
    TEXT_IDENTIFIER_COLUMNS,
)
from final_etl_handoff import build_star_schema_tables
from star_schema_db import LOAD_ORDER, load_runtime_snapshot


BASELINE_PATH = FINAL_OUTPUT_DIR / "prepared_transactions.csv"
BATCH_COLUMNS = [
    "batch_id", "source_filename", "uploaded_at", "staged_rows",
    "within_upload_duplicates", "existing_exact_rows", "new_rows",
    "possible_correction_rows", "ambiguous_identity_rows", "active_rows",
]
IDENTITY_COLUMNS = ("Order ID", "product_key", "order_date")
# Shopee does not export a stable transaction-line identifier. This compact
# fingerprint deliberately uses the order/product identifiers, transactional
# timestamps, status/return state, quantities, and monetary measures that
# distinguish an operational sales line. Filename/folder and derived labels are
# excluded so re-exports remain idempotent. Full source-field comparison would
# add significant memory/latency at 226k rows without supplying a true line ID.
CONTENT_COLUMNS = (
    "Order ID", "Order Status", "Return / Refund Status", "Tracking Number*",
    "Order Creation Date", "Order Paid Time", "Order Complete Time",
    "Product Name", "Variation Name", "Parent SKU Reference No.", "SKU Reference No.",
    "Quantity", "Returned quantity", "Original Price", "Deal Price",
    "Total Buyer Payment", "Total Discount(PHP)", "Products' Price Paid by Buyer (PHP)",
    "Grand Total",
)
MISSING = "<TESPH:missing>"


def runtime_database_lock(db_path: Path, *, timeout: float = 30) -> FileLock:
    """Return a cross-process lock shared by upload workflows for one database."""
    destination = Path(db_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(f"{destination}.upload.lock", timeout=timeout)


@dataclass(frozen=True)
class RuntimeState:
    """The durable active snapshot or a read-only baseline bootstrap."""

    transactions: pd.DataFrame
    batches: pd.DataFrame
    dataset_id: str
    bootstrapped_from_baseline: bool


@dataclass(frozen=True)
class ReconciliationResult:
    """Conservative result of comparing validated staging with active history."""

    transactions: pd.DataFrame
    batches: pd.DataFrame
    summary: dict[str, int | str]
    dataset_id: str


def _normalized_column(values: pd.Series, column: str) -> pd.Series:
    """Normalize equivalent CSV/XLSX representations without changing data."""
    # ETL preserves source text after strict validation. Keeping ordinary text
    # literal here makes the runtime comparison inexpensive at historical
    # scale; only CSV/XLSX-sensitive date and numeric representations need
    # cross-format normalization.
    result = values.astype("string").fillna(MISSING)
    # CSV parsing commonly represents empty Shopee cells as ``NaN`` whereas
    # XLSX parsing preserves them as empty strings.  They are the same absent
    # source value for reconciliation purposes (and neither is a business
    # field value), so normalize both representations before hashing.
    result = result.mask(result.str.strip().eq(""), MISSING)
    # CSV inference can serialize a purely numeric optional SKU such as ``0``
    # as ``0.0``.  Canonicalize only integer-valued identifier text; values
    # with leading zeroes (which can be meaningful SKU codes) are preserved.
    if column in TEXT_IDENTIFIER_COLUMNS:
        result = result.mask(
            result.str.fullmatch(r"(?:0|[1-9]\d*)\.0+", na=False),
            result.str.replace(r"\.0+$", "", regex=True),
        )
    present = result.ne(MISSING)
    if column in DATE_SOURCE_COLUMNS:
        # Seller Centre denotes a missing optional timestamp as ``-`` in some
        # XLSX exports; the governed CSV represents the same cell as empty.
        # These are accepted missing values, not malformed dates.
        result = result.mask(result.str.strip().eq("-"), MISSING)
        present = result.ne(MISSING)
        parsed = pd.to_datetime(values, errors="coerce", format="mixed")
        result.loc[present & parsed.notna()] = parsed.loc[present & parsed.notna()].dt.strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )
    elif column in MEASURE_COLUMNS:
        numeric = pd.to_numeric(values, errors="coerce")
        valid = present & numeric.notna()
        result.loc[valid] = numeric.loc[valid].map(lambda value: format(float(value), ".15g"))
    return result


def _fingerprints(frame: pd.DataFrame, columns: tuple[str, ...] | list[str]) -> pd.Series:
    """Return stable SHA-256 content fingerprints at historical-data scale."""
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError("Fingerprint fields are missing: " + ", ".join(missing))
    # Feed the exact same delimiter-separated payload a column at a time. This
    # avoids holding millions of Python strings from every column simultaneously.
    digests = [sha256() for _ in range(len(frame))]
    for position, column in enumerate(columns):
        separator = "\x1f" if position else ""
        values = _normalized_column(frame[column], column).tolist()
        for digest, value in zip(digests, values):
            digest.update((separator + str(value)).encode("utf-8"))
    return pd.Series(
        (digest.hexdigest() for digest in digests),
        index=frame.index,
        dtype="string",
    )


def payload_fingerprints(frame: pd.DataFrame) -> pd.Series:
    """Stable line-content candidate fingerprint excluding provenance/labels."""
    return _fingerprints(frame, list(CONTENT_COLUMNS))


def business_identity_fingerprints(frame: pd.DataFrame) -> pd.Series:
    """Conservative possible-line identity used only to quarantine conflicts.

    Order ID alone is not a line key.  The deterministic product key and order
    date narrow possible matches, but duplicate identities remain ambiguous and
    are never automatically overwritten.
    """
    return _fingerprints(frame, list(IDENTITY_COLUMNS))


def _dataset_id(payloads: pd.Series) -> str:
    digest = sha256()
    for value in sorted(payloads.astype(str).tolist()):
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return "active-" + digest.hexdigest()[:20]


def _empty_batches() -> pd.DataFrame:
    return pd.DataFrame(columns=BATCH_COLUMNS)


def _restore_prepared_dtypes(transactions: pd.DataFrame) -> pd.DataFrame:
    """Restore the canonical bool contract after SQLite's integer round-trip."""
    result = transactions.copy()
    for column in ("has_negative_financial_value", *STATUS_COLUMNS):
        values = result[column].astype("string").str.strip().str.casefold()
        valid = values.isin(("0", "1", "false", "true"))
        if not valid.all():
            raise RuntimeError(f"Runtime database has invalid boolean values in {column}")
        result[column] = values.isin(("1", "true"))
    return result


def _read_runtime_database(db_path: Path) -> RuntimeState | None:
    if not db_path.is_file():
        return None
    # ``sqlite3.Connection``'s context manager commits/rolls back but does
    # not close the handle. Closing it explicitly is required on Windows
    # before the next atomic ``os.replace`` of the runtime snapshot.
    with closing(sqlite3.connect(db_path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not tables:
            return None
        required = {"prepared_transactions", "ingestion_batches", "runtime_metadata"}
        if not required.issubset(tables):
            raise RuntimeError("Runtime database is missing active transaction tables")
        # Chunk fetching avoids SQLite retaining a Python tuple for every row
        # while pandas also materializes the full transaction frame.
        transactions = _restore_prepared_dtypes(
            pd.concat(pd.read_sql_query("SELECT * FROM prepared_transactions", conn, chunksize=10_000), ignore_index=True).infer_objects()
        )
        batches = pd.read_sql_query("SELECT * FROM ingestion_batches ORDER BY uploaded_at, batch_id", conn)
        metadata = dict(conn.execute("SELECT key, value FROM runtime_metadata"))
    validate_final_schema(transactions.columns, "prepared_transactions")
    if list(batches.columns) != BATCH_COLUMNS:
        raise RuntimeError("Runtime database has an invalid ingestion audit schema")
    return RuntimeState(
        transactions=transactions,
        batches=batches,
        dataset_id=metadata.get("dataset_id") or _dataset_id(payload_fingerprints(transactions)),
        bootstrapped_from_baseline=False,
    )


def load_active_state(
    *, db_path: Path = RUNTIME_DB_PATH, baseline_path: Path = BASELINE_PATH
) -> RuntimeState:
    """Load the active runtime snapshot, or read the immutable baseline once."""
    persisted = _read_runtime_database(Path(db_path))
    if persisted is not None:
        return persisted
    baseline = load_prepared_transactions(baseline_path.parent)
    return RuntimeState(
        transactions=baseline,
        batches=_empty_batches(),
        dataset_id=_dataset_id(payload_fingerprints(baseline)),
        bootstrapped_from_baseline=True,
    )


def reconcile_validated_upload(
    staging: pd.DataFrame,
    active: RuntimeState,
    *,
    source_filename: str,
) -> ReconciliationResult:
    """Safely add only content absent from active history.

    Exact payload matches are idempotent regardless of filename. A changed row
    sharing a possible business identity is not updated: unique candidates are
    reported as possible corrections and multi-line candidates as ambiguous.
    This avoids silently replacing a legitimate multi-line Shopee order where
    the export supplies no stable line identifier.
    """
    validate_final_schema(staging.columns, "prepared_transactions")
    validate_final_schema(active.transactions.columns, "prepared_transactions")
    staged_payloads = payload_fingerprints(staging)
    staged_identities = business_identity_fingerprints(staging)
    active_payloads = payload_fingerprints(active.transactions)
    active_identities = business_identity_fingerprints(active.transactions)

    active_payload_set = set(active_payloads.astype(str))
    identity_counts = active_identities.astype(str).value_counts().to_dict()
    staged_seen_payloads: set[str] = set()
    staged_identity_counts: dict[str, int] = {}
    accepted_positions: list[int] = []
    within_duplicates = existing_exact = possible_corrections = ambiguous = 0

    for position, (payload, identity) in enumerate(zip(staged_payloads, staged_identities)):
        payload_text, identity_text = str(payload), str(identity)
        if payload_text in staged_seen_payloads:
            within_duplicates += 1
            continue
        staged_seen_payloads.add(payload_text)
        if payload_text in active_payload_set:
            existing_exact += 1
            continue
        existing_identity_count = int(identity_counts.get(identity_text, 0))
        staged_identity_count = int(staged_identity_counts.get(identity_text, 0))
        if existing_identity_count == 1:
            possible_corrections += 1
            continue
        if existing_identity_count > 1 or staged_identity_count > 0:
            ambiguous += 1
            continue
        accepted_positions.append(position)
        staged_identity_counts[identity_text] = 1

    additions = staging.iloc[accepted_positions].copy()
    consolidated = pd.concat([active.transactions, additions], ignore_index=True) if len(additions) else active.transactions
    # Accepted payloads were already calculated above; concatenation changes no
    # source values. Do not hash the entire active history a second time.
    consolidated_payloads = pd.concat([active_payloads, staged_payloads.iloc[accepted_positions]], ignore_index=True)
    result_dataset_id = _dataset_id(consolidated_payloads)
    batch_id = "batch-" + _dataset_id(staged_payloads).removeprefix("active-")
    summary: dict[str, int | str] = {
        "batch_id": batch_id,
        "source_filename": source_filename,
        "staged_rows": len(staging),
        "within_upload_duplicates": within_duplicates,
        "existing_exact_rows": existing_exact,
        "new_rows": len(additions),
        "possible_correction_rows": possible_corrections,
        "ambiguous_identity_rows": ambiguous,
        "active_rows": len(consolidated),
    }
    batch = pd.DataFrame([{
        **summary,
        "uploaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }])[BATCH_COLUMNS]
    batches = pd.concat([active.batches, batch], ignore_index=True)
    # Re-uploading equivalent contents changes no data, but keeping one audit
    # row per content batch makes the local ledger deterministic and compact.
    batches = batches.drop_duplicates("batch_id", keep="first").reset_index(drop=True)
    return ReconciliationResult(
        transactions=consolidated,
        batches=batches,
        summary=summary,
        dataset_id=result_dataset_id,
    )


def publish_validated_upload(
    staging: pd.DataFrame,
    *,
    source_filename: str,
    db_path: Path = RUNTIME_DB_PATH,
    baseline_path: Path | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, int | str], str]:
    """Reconcile staging then atomically publish active prepared data and stars."""
    baseline_path = Path(baseline_path) if baseline_path is not None else BASELINE_PATH
    with runtime_database_lock(Path(db_path)):
        active = load_active_state(db_path=db_path, baseline_path=baseline_path)
        result = reconcile_validated_upload(staging, active, source_filename=source_filename)
        # ``build_star_schema_tables`` accepts transformed fields and adds the two
        # governed labels itself. The active handoff already has those labels, so
        # remove only them before rebuilding the materialized view.
        star_input = result.transactions.drop(
            columns=["final_base_product_name", "final_category"], errors="ignore"
        )
        rebuilt = build_star_schema_tables(star_input)
        prepared = rebuilt.pop("prepared_transactions")
        validate_final_schema(prepared.columns, "prepared_transactions")
        final_dataset_id = _dataset_id(payload_fingerprints(prepared))
        counts = load_runtime_snapshot(
            rebuilt,
            prepared,
            result.batches,
            {
                "dataset_id": final_dataset_id,
                "baseline_path": str(Path(baseline_path).resolve()),
                "baseline_immutable": "true",
                "reconciliation_policy": "exact-content-add-only; possible-corrections-quarantined",
            },
            Path(db_path),
        )
        summary = dict(result.summary)
        summary["active_rows"] = len(prepared)
        summary["star_fact_rows"] = counts["fact_sales"]
        from mca_refresh import review_after_sales
        try:
            review_after_sales(prepared, db_path)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Sales saved but return/refund review is pending")
            summary["return_review_status"] = "pending; MCA outputs unavailable until successful refresh"
        return rebuilt, prepared, summary, final_dataset_id


def reset_active_to_baseline(
    *,
    db_path: Path = RUNTIME_DB_PATH,
    baseline_path: Path = BASELINE_PATH,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, str]:
    """Atomically reset the runtime active transactions database to the governed baseline."""
    baseline_path = Path(baseline_path)
    db_path = Path(db_path)
    with runtime_database_lock(db_path):
        baseline = load_prepared_transactions(baseline_path.parent)
        validate_final_schema(baseline.columns, "prepared_transactions")
        star_input = baseline.drop(
            columns=["final_base_product_name", "final_category"], errors="ignore"
        )
        rebuilt = build_star_schema_tables(star_input)
        prepared = rebuilt.pop("prepared_transactions")
        validate_final_schema(prepared.columns, "prepared_transactions")
        final_dataset_id = _dataset_id(payload_fingerprints(prepared))
        load_runtime_snapshot(
            rebuilt,
            prepared,
            _empty_batches(),
            {
                "dataset_id": final_dataset_id,
                "baseline_path": str(baseline_path.resolve()),
                "baseline_immutable": "true",
                "reconciliation_policy": "exact-content-add-only; possible-corrections-quarantined",
            },
            db_path,
        )
        from mca_refresh import review_after_sales
        try:
            review_after_sales(prepared, db_path)
        except Exception:
            pass
        return rebuilt, prepared, final_dataset_id
