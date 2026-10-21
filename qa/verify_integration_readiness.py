"""Build a separate corrected handoff and independently check its calculations."""
from pathlib import Path
import hashlib
import json
import math
import sqlite3
import sys
import zipfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from etl import load_prepared_transactions
from star_schema_db import (read_runtime_star_schema, load_runtime_snapshot,
                            read_runtime_snapshot, INGESTION_BATCH_COLUMNS)
from runtime_data_store import load_active_state, payload_fingerprints, _dataset_id
from analytics_data import load_transactions
from forecasting_pipeline import run_forecasting_pipeline
from three_criterion_mca import Coverage, evaluate_requests, rank_scenarios, RATE

OUT = ROOT / "validation_outputs/integration_readiness"
PRIVATE = ROOT / ".artifacts/qa/integration_readiness"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_storage_equal(expected, actual):
    """Exact values/order; allow SQLite REAL to represent numeric 35 as 35.0."""
    assert list(expected.columns) == list(actual.columns)
    assert len(expected) == len(actual)
    for column in expected:
        left, right = expected[column], actual[column]
        if pd.api.types.is_numeric_dtype(left) and not pd.api.types.is_bool_dtype(left):
            pd.testing.assert_series_equal(left, pd.to_numeric(right, errors="raise"),
                                           check_dtype=False, check_exact=True)
        else:
            pd.testing.assert_series_equal(left.fillna("").astype(str),
                                           right.fillna("").astype(str))


def inventory():
    records = []
    for path in [ROOT / "runtime_data/active_transactions.db",
                 *sorted((ROOT / ".artifacts/qa").glob("*.db"))]:
        row = {"path": str(path.relative_to(ROOT)), "exists": path.exists()}
        if path.exists():
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                row["counts"] = {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                                 for name in ("prepared_transactions", "fact_sales", "dim_product") if name in tables}
            row["sha256"] = sha(path)
        records.append(row)
    return records


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    source = ROOT / "final_outputs/prepared_transactions.csv"
    source_hash = sha(source)
    result = {"source_sha256": source_hash, "available_databases": inventory()}
    full = load_prepared_transactions()
    candidate = load_transactions(ROOT / ".artifacts/qa/sku_recovery/source_exact_candidate.csv")
    old = load_transactions()
    pd.testing.assert_frame_equal(old.drop(columns="SKU Reference No."),
                                  candidate.drop(columns="SKU Reference No."))
    changed = old["SKU Reference No."].fillna("").ne(candidate["SKU Reference No."].fillna(""))
    assert changed.sum() == 112
    pd.testing.assert_series_equal(full.product_key.astype("string"), candidate.product_key)
    corrected = full.copy()
    corrected["SKU Reference No."] = candidate["SKU Reference No."]
    tables = read_runtime_star_schema(ROOT / ".artifacts/qa/full_seed.db")
    assert len(tables["fact_sales"]) == len(corrected) == 226203
    for key in corrected.loc[changed, "product_key"].unique():
        values = sorted(set(corrected.loc[corrected.product_key.eq(key), "SKU Reference No."].dropna()))
        tables["dim_product"].loc[tables["dim_product"].product_key.eq(key), "SKU"] = " | ".join(values)
    for name, frame in {**tables, "prepared_transactions": corrected}.items():
        frame.to_csv(PRIVATE / f"{name}.csv", index=False)
    reloaded = load_prepared_transactions(PRIVATE)
    # Compare the full schema, every value, and row order after serialization.
    pd.testing.assert_frame_equal(corrected.fillna("").astype(str), reloaded.fillna("").astype(str))
    dataset_id = _dataset_id(payload_fingerprints(corrected))
    db = PRIVATE / "corrected_candidate.db"
    counts = load_runtime_snapshot(tables, corrected,
        pd.DataFrame(columns=INGESTION_BATCH_COLUMNS),
        {"dataset_id": dataset_id, "baseline_sha256": source_hash,
         "purpose": "Isolated provisional SKU restoration candidate"}, db)
    db_tables, db_prepared = read_runtime_snapshot(db)
    assert_storage_equal(corrected, db_prepared)
    for name in tables:
        assert_storage_equal(tables[name], db_tables[name])
    active = load_active_state(db_path=db, baseline_path=PRIVATE / "prepared_transactions.csv")
    assert len(active.transactions) == len(corrected)
    result["candidate"] = {"rows": len(corrected), "columns": len(corrected.columns),
        "restored_references": int(changed.sum()), "database_counts": counts,
        "dataset_id": dataset_id, "all_csv_db_values_equal": True}
    print("Corrected full-schema CSV/database reconciliation passed", flush=True)
    mapping = pd.read_csv(ROOT / ".artifacts/qa/sku_recovery/after_mapping.csv", dtype="string")
    forecasts = run_forecasting_pipeline(candidate, mapping=mapping)
    forecasts["validation_detail"].to_csv(PRIVATE / "validation_detail.csv", index=False)
    # Independent model formulas on source-derived daily demand, not production kernels.
    truth = lambda s: s.astype(str).str.lower().isin(["true", "1"])
    demand = pd.to_numeric(corrected.Quantity).where(
        truth(corrected.is_completed) | truth(corrected.is_returned), 0)
    dates = pd.to_datetime(corrected["Order Creation Date"], format="mixed").dt.normalize()
    end = dates.max()
    forecast_checks = []
    for sku, output in forecasts["forecast_output"].groupby("SKU"):
        key = mapping.loc[mapping.SKU.eq(sku), "product_key"].iloc[0]
        mask = corrected.product_key.eq(key)
        observed = pd.DataFrame({"date": dates[mask], "units": demand[mask]}).groupby("date").units.sum()
        y = observed.reindex(pd.date_range(observed.index.min(), end), fill_value=0).astype(float).tolist()
        method = output.Method.iloc[0]
        if method == "Moving Average":
            w = int(output["MA Window"].iloc[0])
            manual = y.copy()
            for _ in range(len(output)):
                manual.append(sum(manual[-w:]) / w)
            expected = manual[-len(output):]
        elif method == "Exponential Smoothing":
            alpha = float(output["ES Alpha"].iloc[0])
            level = y[0]
            for value in y[1:]:
                level = alpha * value + (1 - alpha) * level
            expected = [level] * len(output)
        else:
            n = len(y)
            xmean, ymean = (n - 1) / 2, sum(y) / n
            slope = sum((i - xmean) * (v - ymean) for i, v in enumerate(y)) / sum((i - xmean)**2 for i in range(n))
            expected = [max(0, ymean + slope * (i - xmean)) for i in range(n, n + len(output))]
        np.testing.assert_allclose(output.Forecast, expected, atol=1e-10, rtol=1e-10)
        forecast_checks.append({"SKU": sku, "Method": method, "History Days": len(y),
                                "Maximum Absolute Difference": float(np.max(np.abs(np.array(expected)-output.Forecast)))})
    pd.DataFrame(forecast_checks).to_csv(OUT / "independent_forecast_checks.csv", index=False)
    metrics = forecasts["validation_metrics"]
    for (sku, method), detail in forecasts["validation_detail"].groupby(["SKU", "Method"]):
        a = detail.Actual.to_numpy(float)
        p = detail.Forecast.to_numpy(float)
        e = a-p
        row = metrics.loc[metrics.SKU.eq(sku) & metrics.Method.eq(method)].iloc[0]
        np.testing.assert_allclose([row.MAE, row.RMSE, row.MAPE],
            [sum(abs(e))/len(e), math.sqrt(sum(e*e)/len(e)),
             sum(abs(e)/np.maximum(abs(a),1))/len(e)*100], atol=1e-10)
        assert pd.isna(row.R2) if len(a)<2 or np.var(a)==0 else np.isclose(row.R2, 1-sum(e*e)/sum((a-a.mean())**2))
    print("Independent forecast and validation-metric checks passed", flush=True)
    with zipfile.ZipFile(ROOT.parent / "RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip") as z:
        snapshot = pd.read_csv(z.open(next(n for n in z.namelist()
            if n.endswith("/prepared_return_refund_backend.csv"))), dtype=str, keep_default_na=False)
    coverage = Coverage("2020-05-22","2026-04-24","2020-05-01","2026-04-24","2026-10-15","2026-10-16", established=True)
    admitted = mapping.loc[mapping.SKU.notna()].copy()
    rates, review = evaluate_requests(candidate, snapshot, admitted, coverage)
    unconfirmed, _ = evaluate_requests(candidate, snapshot, admitted,
        Coverage(**{**coverage.__dict__, "established": False}))
    assert unconfirmed[RATE].isna().all()
    matched = snapshot.loc[snapshot.product_key.isin(admitted.product_key)]
    assert len(matched)==1 and matched["Return / Refund Status"].eq("Request Cancelled").all()
    independent_units = pd.DataFrame({"key": corrected.product_key, "units": demand}).groupby("key").units.sum()
    for _, row in rates.iterrows():
        denominator = independent_units.get(row.product_key, 0)
        assert row["Eligible Ordered Units"] == denominator
        assert row["Recorded Refunded Units"] == 0
        assert pd.isna(row[RATE]) if denominator == 0 else row[RATE] == 0
    audit = pd.read_csv(ROOT / "validation_outputs/sku_recovery/after_mca_audit.csv")
    scenarios, comparison, sensitivity = rank_scenarios(audit)
    eligible = audit.dropna(subset=["Sales Velocity", "Forecasted Demand", RATE])
    cols = ["Sales Velocity", "Forecasted Demand", RATE]
    for label, weights in (("equal_thirds", [1/3]*3), ("volume_quality", [.25,.25,.5])):
        manual = []
        for _, row in eligible.iterrows():
            norm = []
            for i, col in enumerate(cols):
                lo, hi = eligible[col].min(), eligible[col].max()
                norm.append(.5 if hi == lo else ((hi-row[col]) if i==2 else (row[col]-lo))/(hi-lo))
            manual.append((row.SKU, sum(w*v for w,v in zip(weights,norm))))
        manual.sort(key=lambda p:(-p[1],p[0]))
        actual = scenarios[label]
        assert list(actual.SKU) == [s for s,v in manual]
        np.testing.assert_allclose(actual["SKU Priority Score"], [v for s,v in manual], atol=1e-12)
        expected_groups = ["High" if i<=math.ceil(len(manual)*.25) else "Medium"
            if i<=math.ceil(len(manual)*.75) else "Low" for i in range(1,len(manual)+1)]
        assert list(actual["Priority Level"]) == expected_groups
        actual.to_csv(OUT / f"independently_checked_{label}.csv", index=False)
    result["independent_checks"] = {"forecast_skus":len(forecast_checks),
        "validation_metric_rows":len(metrics), "return_denominators":len(rates),
        "coverage_false_all_rates_unavailable":True, "mca_rankings_per_scenario":len(eligible),
        "weight_scenarios_checked":2, "sensitivity":sensitivity}
    result["coverage_limitation"] = "Confirmed selected request-date files only; not lifetime refund coverage or a simultaneous October update cutoff. TA baseline acceptance pending."
    result["source_unchanged"] = sha(source)==source_hash
    assert result["source_unchanged"]
    result["candidate_files"] = {p.name:sha(p) for p in PRIVATE.glob("*") if p.suffix in (".csv",".db")}
    (OUT / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
