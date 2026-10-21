"""Isolated real-data upload benchmarks. Run from the repository root.

Fixtures contain client data and stay in ignored .artifacts/qa. Each trial runs
in a fresh process and copies the same starting database before timing begins.
No normal runtime database or governed source file is modified.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / ".artifacts" / "qa"
EVIDENCE = ROOT / "validation_outputs" / "integration_qa"


def memory():
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize / (1024 ** 3)


def seed(prepared, path):
    import pandas as pd
    from final_etl_handoff import build_star_schema_tables
    from runtime_data_store import BATCH_COLUMNS, _dataset_id, payload_fingerprints
    from star_schema_db import load_runtime_snapshot
    print(f"Building isolated seed: {len(prepared)} rows", flush=True)
    tables = build_star_schema_tables(prepared.drop(columns=["final_base_product_name", "final_category"]))
    prepared = tables.pop("prepared_transactions")
    dataset_id = _dataset_id(payload_fingerprints(prepared))
    load_runtime_snapshot(tables, prepared, pd.DataFrame(columns=BATCH_COLUMNS), {"dataset_id": dataset_id}, path)


def prepare():
    from etl import load_prepared_transactions
    from etl_config import SOURCE_COLUMNS
    WORK.mkdir(parents=True, exist_ok=True)
    data = load_prepared_transactions()
    data[list(SOURCE_COLUMNS)].to_csv(WORK / "full_repeat.csv", index=False)
    # Remove real, uniquely identified lines to create a reproducible 10,000-row
    # increment. The upload restores them; no fabricated orders are introduced.
    identity = ["Order ID", "product_key", "order_date"]
    additions = data.loc[~data.duplicated(identity, keep=False)].tail(10_000)
    assert len(additions) == 10_000
    additions[list(SOURCE_COLUMNS)].to_csv(WORK / "incremental.csv", index=False)
    seed(data, WORK / "full_seed.db")
    seed(data.drop(index=additions.index), WORK / "incremental_seed.db")
    manifest = {"baseline_rows": len(data), "incremental_rows": len(additions),
                "baseline_sha256": hashlib.sha256((ROOT / "final_outputs/prepared_transactions.csv").read_bytes()).hexdigest()}
    (WORK / "fixtures.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest), flush=True)


def worker(scenario, profile):
    import pandas as pd
    from etl_streamlit import run_etl_from_upload
    import cProfile
    profiler = cProfile.Profile() if profile else None
    events = []
    db = WORK / f"trial_{scenario}.db"
    if scenario in {"repeat", "incremental"}:
        shutil.copyfile(WORK / ("full_seed.db" if scenario == "repeat" else "incremental_seed.db"), db)
        payload = (WORK / ("full_repeat.csv" if scenario == "repeat" else "incremental.csv")).read_bytes()
    started = time.perf_counter()
    if profiler:
        profiler.enable()
    if scenario == "forecast":
        from forecasting_pipeline import run_forecasting_pipeline
        result = run_forecasting_pipeline()
        counts = {"forecast_rows": len(result["forecast_output"]), "sku_count": result["forecast_output"].SKU.nunique()}
        assert counts["forecast_rows"] == 413
    else:
        def progress(step, name, message):
            event = {"seconds": round(time.perf_counter() - started, 3), "message": message,
                     "peak_working_set_gib": round(memory(), 3)}
            events.append(event)
            print(json.dumps(event), flush=True)
        result = run_etl_from_upload(payload, "actual_history.csv", db_path=db, on_step=progress)
        assert result.success, result.error_message
        counts = result.reconciliation_summary
        assert counts["new_rows"] == (0 if scenario == "repeat" else 10_000), counts
        assert counts["active_rows"] == 226_203, counts
        assert len(result.star_schema["fact_sales"]) == 226_203
        assert result.reused_existing_outputs == (scenario == "repeat")
    elapsed = time.perf_counter() - started
    if profiler:
        profiler.disable()
        import pstats
        with (EVIDENCE / f"{profile}_{scenario}_profile.txt").open("w") as out:
            pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(45)
    peak = memory()
    # Persistence and identity checks are outside the timed upload pipeline.
    if scenario != "forecast":
        with closing(sqlite3.connect(db)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
            assert conn.execute("SELECT count(*) FROM prepared_transactions").fetchone()[0] == 226_203
        from runtime_data_store import load_active_state, payload_fingerprints
        # Byte-representation details may differ after SQLite roundtrip; compare
        # canonical transaction fingerprints, quantities and money instead.
        from etl import load_prepared_transactions
        original = load_prepared_transactions()
        persisted = load_active_state(db_path=db).transactions
        assert sorted(payload_fingerprints(persisted)) == sorted(payload_fingerprints(original))
        for col in ("Quantity", "Returned quantity", "Total Buyer Payment", "Grand Total"):
            assert abs(pd.to_numeric(persisted[col]).sum() - pd.to_numeric(original[col]).sum()) < 1e-6, col
    record = {"scenario": scenario, "seconds": round(elapsed, 3), "peak_working_set_gib": round(peak, 3),
              "counts": counts, "events": events, "checks": "passed", "profiled": bool(profile)}
    print("RESULT " + json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--worker", choices=["repeat", "incremental", "forecast"])
    parser.add_argument("--scenarios", nargs="+", default=["repeat", "incremental", "forecast"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--label", default="final")
    parser.add_argument("--profile")
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        prepare()
        return
    if args.worker:
        worker(args.worker, args.profile)
        return
    records = []
    for scenario in args.scenarios:
        for run in range(1, args.runs + 1):
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", scenario]
            if args.profile:
                command += ["--profile", args.profile]
            log = EVIDENCE / f"{args.label}_{scenario}_{run}.log"
            print(f"Running {scenario} {run}/{args.runs}; progress in {log.name}", flush=True)
            with log.open("w") as stream:
                process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
            if process.returncode:
                raise RuntimeError(f"Benchmark failed: {log}")
            record = json.loads(next(line[7:] for line in log.read_text().splitlines() if line.startswith("RESULT ")))
            records.append(record)
            print(json.dumps(record), flush=True)
    summary = {scenario: {"median_seconds": statistics.median(r["seconds"] for r in records if r["scenario"] == scenario),
                          "max_peak_working_set_gib": max(r["peak_working_set_gib"] for r in records if r["scenario"] == scenario)} for scenario in args.scenarios}
    report = {"assessment_date": "2026-10-10", "platform": platform.platform(), "python": sys.version,
              "fixtures": json.loads((WORK / "fixtures.json").read_text()), "runs": records, "summary": summary,
              "scope": "Backend upload ETL plus reconciliation and SQLite publication; excludes post-upload analytics/forecast rendering. Peak working set includes worker setup; measured before post-run verification."}
    (EVIDENCE / f"{args.label}_performance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
