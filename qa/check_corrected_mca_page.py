"""Component acceptance using actual corrected-candidate backend outputs."""
from pathlib import Path
import json
import sys
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from utils.state import DEFAULT_STATE, DataStatus


def main():
    data = ROOT / "validation_outputs/sku_recovery"
    audit = pd.read_csv(data / "after_mca_audit.csv")
    rankings = pd.read_csv(data / "after_mca_results.csv")
    forecasts = pd.read_csv(data / "after_forecasts.csv")
    sensitivity = pd.read_csv(data / "after_mca_sensitivity.csv")
    app = AppTest.from_file(ROOT / "pages/product_prioritization.py", default_timeout=30)
    for key, value in {**DEFAULT_STATE, "authenticated": True,
        "_runtime_authority_loaded": True,
        "data_status": DataStatus.DATA_READY.value, "active_dataset_id": "corrected-candidate",
        "forecast_dataset_id": "corrected-candidate", "analytics_dataset_id": "corrected-candidate",
        "analytics_results": {}, "forecast_results": {"forecast_output": forecasts},
        "mca_results": rankings, "mca_audit": audit, "mca_sensitivity": sensitivity}.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    displayed = next(t.value for t in app.dataframe if "SKU Priority Score" in t.value)
    pd.testing.assert_frame_equal(displayed, rankings)
    readiness = next(t.value for t in app.dataframe if "MCA Status" in t.value)
    assert readiness["Recorded Return/Refund Quantity Rate"].eq("N/A").sum() == 1
    assert any("final TA" in caption.value and "not lifetime" in caption.value for caption in app.caption)
    comparison = next(t.value for t in app.dataframe if "Rank Change" in t.value)
    pd.testing.assert_frame_equal(comparison, sensitivity)
    result = {"status": "passed", "ranked_skus": len(displayed), "readiness_rows": len(readiness),
              "checks": ["No page exception", "Exact backend/ranking table equality",
                         "Missing rate displayed as N/A", "Provisional and coverage caveats visible",
                         "Exact backend/sensitivity table equality"],
              "scope": "Current Streamlit page component with real candidate output tables; not Member 3's merged build or browser end-to-end acceptance."}
    (ROOT / "validation_outputs/integration_readiness/page_check.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
