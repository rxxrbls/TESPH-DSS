"""Reproducible real-handoff audit. Run with the repository Python environment."""
from pathlib import Path
import hashlib
import json
import time

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from analytics_data import load_transactions
from active_inventory import build_active_mapping
from forecasting_pipeline import run_forecasting_pipeline
from utils.forecast_display import accuracy_table
from utils.state import DEFAULT_STATE, DataStatus


def main():
    root = Path(__file__).resolve().parent
    output = root / "validation_outputs" / "forecast_accuracy"
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    transactions = load_transactions()
    mapping, _ = build_active_mapping(transactions, as_of="2026-10-08")
    results = run_forecasting_pipeline(transactions, mapping=mapping)
    detail, metrics, best = (results[name] for name in ("validation_detail", "validation_metrics", "best_methods"))
    assert not detail.empty
    assert not detail.duplicated(["SKU", "Method", "Origin", "Step"]).any()
    assert (detail.Origin < detail.Time).all()
    actuals = results["sku_dataset"].set_index(["SKU", "Time"]).Demand
    np.testing.assert_array_equal(detail.Actual, actuals.reindex(pd.MultiIndex.from_frame(detail[["SKU", "Time"]])).values)
    # Reconcile directly to ETL source rows, independently of history preparation.
    source = transactions.merge(mapping[["product_key", "SKU"]], on="product_key", how="inner", validate="many_to_one")
    source["Time"] = pd.to_datetime(source["order_date"]).dt.normalize()
    source["Demand"] = pd.to_numeric(source["Quantity"]).where(source["is_completed"] | source["is_returned"], 0)
    source_totals = source.groupby(["SKU", "Time"]).Demand.sum()
    history = results["sku_dataset"]
    np.testing.assert_array_equal(history.Demand, source_totals.reindex(pd.MultiIndex.from_frame(history[["SKU", "Time"]]), fill_value=0).values)
    for sku, group in detail.groupby("SKU"):
        coverage = [set(zip(g.Origin, g.Time, g.Step)) for _, g in group.groupby("Method")]
        assert len(coverage) == 3 and all(c == coverage[0] for c in coverage)
    for (sku, method), group in detail.groupby(["SKU", "Method"]):
        a, p = group.Actual.to_numpy(), group.Forecast.to_numpy()
        error = a - p
        variance = np.sum((a - a.mean()) ** 2)
        expected = [np.abs(error).mean(), np.sqrt((error ** 2).mean()),
                    100 * (np.abs(error) / np.maximum(np.abs(a), 1)).mean(),
                    np.nan if variance == 0 or len(a) < 2 else 1 - (error ** 2).sum() / variance]
        row = metrics.loc[metrics.SKU.eq(sku) & metrics.Method.eq(method)].iloc[0]
        np.testing.assert_allclose(row[["MAE", "RMSE", "MAPE", "R2"]].to_numpy(dtype=float), expected, rtol=1e-12, atol=0, equal_nan=True)
        assert row["Validation Observations"] == len(a)
        assert row["Zero Actual Count"] == (a == 0).sum()
        assert pd.isna(row["Raw MAPE"]) if (a == 0).any() else np.isclose(row["Raw MAPE"], 100 * (np.abs(error) / a).mean())
    expected_best = metrics.sort_values(["SKU", "MAPE", "RMSE", "Method"]).groupby("SKU").head(1)
    assert dict(zip(best.SKU, best.Method)) == dict(zip(expected_best.SKU, expected_best.Method))
    forecast = results["forecast_output"]
    for _, row in best.iterrows():
        selected = forecast.loc[forecast.SKU.eq(row.SKU)]
        assert selected.Method.eq(row.Method).all()
        for metric in ("MAE", "RMSE", "MAPE", "R2"):
            np.testing.assert_allclose(selected[metric], row[metric], equal_nan=True)
    app = AppTest.from_file(root / "pages/demand_forecast.py", default_timeout=60)
    state = {**DEFAULT_STATE, "authenticated": True, "data_status": DataStatus.DATA_READY.value,
             "prepared_transactions": transactions, "active_dataset_id": "actual-audit",
             "forecast_dataset_id": "actual-audit", "forecast_results": results,
             "_runtime_authority_loaded": True}
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception, list(app.exception)
    displayed = next(item.value for item in app.dataframe if "R² Status" in item.value)
    pd.testing.assert_frame_equal(displayed, accuracy_table(metrics, best, detail))
    for name in ("validation_metrics", "validation_detail", "best_methods", "forecast_output", "methodology", "selection_status", "eligibility"):
        results[name].to_csv(output / f"{name}.csv", index=False)
    displayed.to_csv(output / "frontend_accuracy.csv", index=False)
    summary = {"audit_date": "2026-10-08", "dataset_sha256": hashlib.sha256((root / "final_outputs/prepared_transactions.csv").read_bytes()).hexdigest(),
               "transaction_rows": len(transactions), "validation_rows": len(detail), "metric_rows": len(metrics),
               "forecast_skus": len(best), "forecast_rows": len(forecast),
               "selected_methods": best.Method.value_counts().to_dict(),
               "constant_actual_skus": int(detail.groupby("SKU").Actual.nunique().eq(1).sum()),
               "undefined_r2_rows": int(metrics.R2.isna().sum()),
               "exact_zero_mae_rows": int(metrics.MAE.eq(0).sum()),
               "small_nonzero_mae_rows": int((metrics.MAE.gt(0) & metrics.MAE.lt(.005)).sum()),
               "metric_ranges": json.loads(metrics[["MAE", "RMSE", "MAPE", "R2"]].agg(["min", "max"]).to_json()),
               "history_end": str(results["sku_dataset"].Time.max()),
               "checks": "PASS: independent metrics, common holdout coverage, source actuals, model selection, forecast metric propagation, Streamlit page values",
               "elapsed_seconds": round(time.perf_counter() - started, 3)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
