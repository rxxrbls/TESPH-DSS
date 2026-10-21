"""Real-data readiness and frontend audit for the approved five-criterion MCA."""
from pathlib import Path
import hashlib
import json

import pandas as pd
from streamlit.testing.v1 import AppTest

from active_inventory import build_active_mapping, INVENTORY_PATH
from analytics_data import load_transactions
from analytics_pipeline import run_analytics_pipeline
from forecasting_pipeline import run_forecasting_pipeline
from prescriptive_pipeline import run_prescriptive_pipeline
from methodology_config import MCA_CRITERIA, MCA_WEIGHTS
from utils.state import DEFAULT_STATE, DataStatus


def main():
    root = Path(__file__).resolve().parent
    output = root / "validation_outputs" / "five_criterion_mca"
    output.mkdir(parents=True, exist_ok=True)
    transactions = load_transactions()
    mapping, inventory = build_active_mapping(transactions, as_of="2026-10-12")
    forecasts = run_forecasting_pipeline(transactions, mapping=mapping)
    analytics = run_analytics_pipeline(transactions)
    stock = inventory.loc[inventory.Reason.eq("Eligible current catalog match")].rename(
        columns={"Current Stock": "Stock", "Stock As-Of Date": "stock_as_of"}
    ).copy()
    stock["match_status"] = "candidate"
    stock["mapping_review_required"] = False
    stock["stock_valid"] = True
    results = run_prescriptive_pipeline(transactions, analytics, forecasts, stock, as_of="2026-10-12")
    audit = results["mca_audit"]
    assert len(audit) == forecasts["forecast_output"].SKU.nunique()
    assert results["mca_results"].empty
    assert audit[["Profit Margin", "Supplier Lead Time", "Return Rate"]].isna().all().all()
    assert "Stock-Out Frequency" not in audit
    assert not audit["MCA Eligible"].any()
    app = AppTest.from_file(root / "pages/product_prioritization.py", default_timeout=60)
    state = {**DEFAULT_STATE, "authenticated": True, "data_status": DataStatus.DATA_READY.value,
             "prepared_transactions": transactions, "active_dataset_id": "mca-audit", "forecast_dataset_id": "mca-audit",
             "analytics_dataset_id": "mca-audit", "forecast_results": forecasts, "analytics_results": analytics,
             "mca_results": results["mca_results"], "mca_audit": audit, "_runtime_authority_loaded": True}
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    shown = next(table.value for table in app.dataframe if "MCA Status" in table.value)
    # Streamlit's Arrow transport can convert object strings to StringDtype.
    expected_display = audit.copy()
    for criterion in MCA_CRITERIA:
        expected_display[criterion] = audit[criterion].map(
            lambda value: "N/A" if pd.isna(value) else format(value, ".6g"))
    pd.testing.assert_frame_equal(shown, expected_display, check_dtype=False)
    for name, frame in results.items():
        frame.to_csv(output / f"{name}.csv", index=False)
    summary = {"audit_date": "2026-10-12", "criteria": list(MCA_CRITERIA), "weights": MCA_WEIGHTS, "transaction_rows": len(transactions),
               "transaction_sha256": hashlib.sha256((root / "final_outputs/prepared_transactions.csv").read_bytes()).hexdigest(),
               "stock_sha256": hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest(),
               "forecast_skus": len(audit), "scored_skus": len(results["mca_results"]),
               "risk_rows": len(results["risk_results"]), "recommendation_rows": len(results["recommendation_results"]),
               "status_counts": audit["MCA Status"].value_counts().to_dict(),
               "checks": "PASS: no substituted scores; missing-input audit; historical stock not required; real-data frontend audit matches backend",
               "input_limitations": "No reconciled net-sales/cost ledger, documented supplier lead times or explicit MCA period supplied. The optional MCA lead-time fallback is not approved or enabled. Current catalog is used only for the existing sample mapping/risk path."}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
