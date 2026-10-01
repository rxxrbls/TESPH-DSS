"""ETL orchestrator for Streamlit integration.

Accepts uploaded file bytes, runs the full ETL pipeline in-memory,
and returns Star Schema DataFrames plus validation results.

No Streamlit code. Database persistence is part of a successful ETL run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tempfile

import pandas as pd

from etl import (
    extract_file,
    detect_exact_duplicates,
    detect_missing_values,
    validate_data_types,
    transform_transactions,
    validate_final_schema,
)
from final_etl_handoff import build_star_schema_tables
from etl_config import RUNTIME_DB_PATH
from runtime_data_store import publish_validated_upload


@dataclass
class ETLStepResult:
    """Result of a single ETL step."""
    step_name: str
    step_index: int
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ETLValidationReport:
    """Comprehensive validation results from the ETL pipeline."""
    is_valid: bool
    row_count: int
    column_count: int
    duplicate_count: int
    missing_value_count: int
    data_type_issues: int
    negative_financial_count: int
    schema_validations: dict[str, bool]  # table_name -> valid
    step_results: list[ETLStepResult]
    warnings: list[str]
    errors: list[str]


@dataclass
class ETLResult:
    """Complete ETL pipeline output for session storage."""
    success: bool
    source_filename: str
    star_schema: dict[str, pd.DataFrame]  # fact_sales, dim_*
    prepared_transactions: pd.DataFrame | None
    validation_report: ETLValidationReport
    reconciliation_summary: dict[str, Any] = field(default_factory=dict)
    dataset_id: str | None = None
    error_message: str | None = None
    reused_existing_outputs: bool = False


from utils.etl_errors import get_user_message

def run_etl_from_upload(
    file_bytes: bytes,
    filename: str,
    *,
    on_step: callable | None = None,
    db_path: Path | None = None,
    baseline_path: Path | None = None,
) -> ETLResult:
    """Execute the full ETL pipeline from uploaded file bytes.

    Parameters
    ----------
    file_bytes : bytes
        Raw bytes from st.file_uploader.
    filename : str
        Original filename (used to determine CSV vs XLSX).
    on_step : callable, optional
        Callback ``(step_index: int, step_name: str, message: str) -> None``
        invoked before each step starts. The Streamlit layer uses this
        to update ``set_etl_active_step()`` and render progress.
    db_path : pathlib.Path, optional
        Destination for the local reconciled runtime snapshot. Injection keeps
        tests isolated. The governed ``final_outputs`` baseline is never the
        destination.
    baseline_path : pathlib.Path, optional
        Immutable prepared historical handoff used only when bootstrapping a
        new runtime snapshot. Tests can provide a small isolated baseline.

    Returns
    -------
    ETLResult
        Contains Star Schema tables and the consolidated active prepared
        transactions, plus reconciliation and validation reports.
    """
    steps: list[ETLStepResult] = []
    warnings: list[str] = []
    errors: list[str] = []

    def _notify(index: int, name: str, msg: str) -> None:
        if on_step:
            on_step(index, name, msg)

    # ── Step 0: Ingest ──────────────────────────────────────────────
    _notify(0, "Ingest", "Reading uploaded file...")
    try:
        temp_path = _bytes_to_temp_path(file_bytes, filename)
        raw_df = extract_file(temp_path)
        temp_path.unlink(missing_ok=True)  # Clean up temp file
        # Uploaded monthly exports do not carry the provenance fields used by
        # the canonical handoff. Add their truthful upload provenance once;
        # never replace provenance already present in a combined export.
        if "source_file" not in raw_df.columns:
            raw_df["source_file"] = filename
        if "source_folder" not in raw_df.columns:
            raw_df["source_folder"] = "uploaded"
        
        if raw_df.empty:
            raise ValueError("The file contains no data rows.")
        
        steps.append(ETLStepResult(
            step_name="Ingest", step_index=0, success=True,
            message=f"Extracted {len(raw_df):,} rows × {len(raw_df.columns)} columns",
            details={"row_count": len(raw_df), "column_count": len(raw_df.columns)},
        ))
    except Exception as exc:
        if 'temp_path' in locals():
            temp_path.unlink(missing_ok=True)
            
        error_key = "empty_file" if "no data rows" in str(exc).lower() else "ingestion_failed"
        user_msg = get_user_message(error_key, str(exc))
        
        steps.append(ETLStepResult(
            step_name="Ingest", step_index=0, success=False,
            message=user_msg,
        ))
        return ETLResult(
            success=False, source_filename=filename,
            star_schema={}, prepared_transactions=None,
            validation_report=_build_report(steps, warnings, errors, False),
            error_message=user_msg,
        )

    # ── Step 1: Clean ───────────────────────────────────────────────
    _notify(1, "Clean", "Detecting duplicates and missing values...")
    dup_mask = detect_exact_duplicates(raw_df)
    dup_count = int(dup_mask.sum())
    if dup_count:
        warnings.append(f"{dup_count} exact duplicate rows detected")

    missing_df = detect_missing_values(raw_df)
    missing_count = len(missing_df)

    steps.append(ETLStepResult(
        step_name="Clean", step_index=1, success=True,
        message=f"{dup_count} duplicates, {missing_count} missing-value locations",
        details={"duplicate_count": dup_count, "missing_count": missing_count},
    ))

    # ── Step 2: Validate ────────────────────────────────────────────
    _notify(2, "Validate", "Validating data types and financial values...")
    try:
        type_report = validate_data_types(raw_df)
        type_issues = len(type_report["invalid_values"])
        neg_count = len(type_report["negative_financial_values"])

        if not type_report["valid"]:
            errors.append(f"{type_issues} invalid date/numeric values detected")
            user_msg = get_user_message("data_type_validation_failed", f"{type_issues} invalid values found")
            
            steps.append(ETLStepResult(
                step_name="Validate", step_index=2, success=False,
                message=user_msg,
                details={
                    "invalid_count": type_issues,
                    "negative_financial_count": neg_count,
                    "invalid_values": type_report["invalid_values"].to_dict("records")[:20],
                },
            ))
            return ETLResult(
                success=False, source_filename=filename,
                star_schema={}, prepared_transactions=None,
                validation_report=_build_report(
                    steps, warnings, errors, False,
                    row_count=len(raw_df), column_count=len(raw_df.columns),
                    dup_count=dup_count, missing_count=missing_count,
                    type_issues=type_issues, neg_count=neg_count,
                ),
                error_message=user_msg,
            )

        if neg_count:
            warnings.append(
                f"{neg_count} legitimate negative financial values preserved"
            )

        steps.append(ETLStepResult(
            step_name="Validate", step_index=2, success=True,
            message=f"All types valid; {neg_count} negative financial values preserved",
            details={"negative_financial_count": neg_count},
        ))
    except Exception as exc:
        user_msg = get_user_message("transformation_failed", str(exc))
        steps.append(ETLStepResult(
            step_name="Validate", step_index=2, success=False,
            message=user_msg,
        ))
        return ETLResult(
            success=False, source_filename=filename,
            star_schema={}, prepared_transactions=None,
            validation_report=_build_report(steps, warnings, errors, False, row_count=len(raw_df), column_count=len(raw_df.columns), dup_count=dup_count, missing_count=missing_count),
            error_message=user_msg,
        )

    # ── Step 3: Transform ───────────────────────────────────────────
    _notify(3, "Transform", "Building canonical transactions and star schema...")
    try:
        transformed = transform_transactions(raw_df)
        star_schema = build_star_schema_tables(transformed)
        prepared = star_schema.pop("prepared_transactions", None)

        # Schema validation for each table
        schema_valid = {}
        for table_name, table_df in star_schema.items():
            try:
                validate_final_schema(table_df.columns, table_name)
                schema_valid[table_name] = True
            except ValueError:
                schema_valid[table_name] = False
                errors.append(f"Schema mismatch for {table_name}")

        if prepared is not None:
            try:
                validate_final_schema(prepared.columns, "prepared_transactions")
                schema_valid["prepared_transactions"] = True
            except ValueError:
                schema_valid["prepared_transactions"] = False
                errors.append("Schema mismatch for prepared_transactions")

        steps.append(ETLStepResult(
            step_name="Transform", step_index=3, success=True,
            message=f"Star schema built: {', '.join(f'{k}({len(v):,})' for k, v in star_schema.items())}",
            details={"schema_validations": schema_valid},
        ))
    except Exception as exc:
        user_msg = get_user_message("transformation_failed", str(exc))
        steps.append(ETLStepResult(
            step_name="Transform", step_index=3, success=False,
            message=user_msg,
        ))
        return ETLResult(
            success=False, source_filename=filename,
            star_schema={}, prepared_transactions=None,
            validation_report=_build_report(steps, warnings, errors, False, row_count=len(raw_df), column_count=len(raw_df.columns), dup_count=dup_count, missing_count=missing_count, type_issues=type_issues, neg_count=neg_count),
            error_message=user_msg,
        )

    # ── Step 4: Load ────────────────────────────────────────────────
    # This step has several time-consuming sub-phases.  Each _notify call
    # pushes an incremental status update to the Streamlit browser so the
    # user can see actual progress rather than a frozen message.
    _notify(4, "Load", "Load / Preparing to reconcile upload with active history...")
    all_valid = all(schema_valid.values()) and not errors

    db_loaded = False
    db_counts = {}
    reconciliation_summary: dict[str, Any] = {}
    dataset_id: str | None = None

    if not all_valid:
        user_msg = get_user_message("schema_validation_failed")
    else:
        user_msg = "Validated upload reconciled with active history"
        try:
            from runtime_data_store import (
                BASELINE_PATH as _DEFAULT_BASELINE,
                load_active_state as _load_active,
                reconcile_validated_upload as _reconcile,
                payload_fingerprints as _fp,
                runtime_database_lock as _runtime_database_lock,
                _dataset_id as _did,
            )
            from star_schema_db import (
                load_runtime_snapshot as _load_snap,
                read_runtime_snapshot as _read_snap,
                record_ingestion_batch as _record_batch,
            )

            _db_path = Path(db_path) if db_path is not None else RUNTIME_DB_PATH
            _bl_path = (
                Path(baseline_path) if baseline_path is not None else _DEFAULT_BASELINE
            )

            runtime_lock = _runtime_database_lock(_db_path)
            runtime_lock.acquire(timeout=30)
            runtime_lock_acquired = True

            # Sub-phase 1: load the active runtime snapshot (may read a large DB).
            _notify(
                4, "Load",
                "Load / Reading active transaction snapshot from runtime database..."
            )
            active = _load_active(db_path=_db_path, baseline_path=_bl_path)

            # Sub-phase 2: reconcile staged rows against the active history.
            _notify(
                4, "Load",
                f"Load / Reconciling {len(prepared):,} staged rows against "
                f"{len(active.transactions):,} active rows..."
            )
            reconciled = _reconcile(prepared, active, source_filename=filename)

            zero_new_rows = (
                not active.bootstrapped_from_baseline
                and reconciled.summary.get("new_rows", 0) == 0
                and reconciled.dataset_id == active.dataset_id
            )

            if zero_new_rows:
                _notify(
                    4, "Load",
                    "Load / Reusing the published runtime snapshot; no new authoritative rows were detected..."
                )
                star_schema, prepared = _read_snap(_db_path)
                batch_id = reconciled.summary["batch_id"]
                audit_batch = reconciled.batches.loc[
                    reconciled.batches["batch_id"].eq(batch_id)
                ].iloc[[-1]]
                _notify(
                    4, "Load",
                    "Load / Recording the validated ingestion batch without republishing the active snapshot..."
                )
                _record_batch(
                    audit_batch,
                    expected_dataset_id=active.dataset_id,
                    db_path=_db_path,
                )
                _summary = dict(reconciled.summary)
                _summary["active_rows"] = len(prepared)
                _summary["star_fact_rows"] = len(star_schema["fact_sales"])
                reconciliation_summary = _summary
                dataset_id = active.dataset_id
                db_counts = {name: len(table) for name, table in star_schema.items()}
                db_loaded = True
                reused_existing_outputs = True
            else:
                # Sub-phase 3: rebuild the complete star schema from merged rows.
                _notify(
                    4, "Load",
                    f"Load / Building star schema from {len(reconciled.transactions):,} "
                    "consolidated rows..."
                )
                star_input = reconciled.transactions.drop(
                    columns=["final_base_product_name", "final_category"], errors="ignore"
                )
                rebuilt = build_star_schema_tables(star_input)
                _prepared = rebuilt.pop("prepared_transactions")
                validate_final_schema(_prepared.columns, "prepared_transactions")
                _final_id = _did(_fp(_prepared))

                # Sub-phase 4: atomically persist the validated snapshot to SQLite.
                _notify(
                    4, "Load",
                    f"Load / Persisting {len(_prepared):,} active rows and star schema to "
                    "runtime database..."
                )
                _counts = _load_snap(
                    rebuilt,
                    _prepared,
                    reconciled.batches,
                    {
                        "dataset_id": _final_id,
                        "baseline_path": str(Path(_bl_path).resolve()),
                        "baseline_immutable": "true",
                        "reconciliation_policy":
                            "exact-content-add-only; possible-corrections-quarantined",
                    },
                    _db_path,
                )
                _summary = dict(reconciled.summary)
                _summary["active_rows"] = len(_prepared)
                _summary["star_fact_rows"] = _counts["fact_sales"]

                star_schema = rebuilt
                prepared = _prepared
                reconciliation_summary = _summary
                dataset_id = _final_id
                db_counts = {name: len(table) for name, table in star_schema.items()}
                db_loaded = True
                reused_existing_outputs = False
        except Exception as exc:
            all_valid = False
            errors.append(f"Database persistence failed: {exc}")
            user_msg = f"Database persistence failed: {exc}"
            import logging
            logging.getLogger(__name__).exception(
                "Runtime database upload failed (database=%s)", locals().get("_db_path")
            )
        finally:
            if locals().get("runtime_lock_acquired", False):
                runtime_lock.release()

    steps.append(ETLStepResult(
        step_name="Load", step_index=4, success=all_valid,
        message=user_msg,
        details={
            "tables_loaded": list(star_schema.keys()),
            "prepared_transactions_rows": len(prepared) if prepared is not None else 0,
            "db_loaded": db_loaded,
            "db_row_counts": db_counts,
            "reconciliation": reconciliation_summary,
        },
    ))

    return ETLResult(
        success=all_valid and db_loaded,
        source_filename=filename,
        star_schema=star_schema,
        prepared_transactions=prepared,
        validation_report=_build_report(
            steps, warnings, errors, all_valid and db_loaded,
            row_count=len(raw_df),
            column_count=len(raw_df.columns),
            dup_count=dup_count,
            missing_count=missing_count,
            type_issues=type_issues,
            neg_count=neg_count,
            schema_valid=schema_valid,
        ),
        reconciliation_summary=reconciliation_summary,
        dataset_id=dataset_id,
        error_message=None if all_valid and db_loaded else user_msg,
        reused_existing_outputs=reused_existing_outputs if "reused_existing_outputs" in locals() else False,
    )


def _bytes_to_temp_path(file_bytes: bytes, filename: str) -> Path:
    """Write bytes to a temporary file for extract_file() compatibility."""
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_name = tmp.name
    return Path(tmp_name)


def _build_report(
    steps, warnings, errors, is_valid, **kwargs
) -> ETLValidationReport:
    return ETLValidationReport(
        is_valid=is_valid,
        row_count=kwargs.get("row_count", 0),
        column_count=kwargs.get("column_count", 0),
        duplicate_count=kwargs.get("dup_count", 0),
        missing_value_count=kwargs.get("missing_count", 0),
        data_type_issues=kwargs.get("type_issues", 0),
        negative_financial_count=kwargs.get("neg_count", 0),
        schema_validations=kwargs.get("schema_valid", {}),
        step_results=steps,
        warnings=warnings,
        errors=errors,
    )
