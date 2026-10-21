"""Read-only correlation diagnostic for saved, dated MCA baseline inputs."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def diagnose(path):
    data = pd.read_csv(path, dtype={"SKU": "string"})
    if data["SKU"].isna().any() or data["SKU"].duplicated().any():
        raise ValueError("Baseline must contain one identified row per SKU")
    values = data[["Sales Velocity", "Forecasted Demand"]].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(values.to_numpy()).all(axis=1)
    pairs = values.loc[finite]
    variable = len(pairs) >= 3 and pairs.nunique().gt(1).all()
    pearson = spearman = None
    if variable:
        scaled = pairs / pairs.abs().max()
        pearson = float(np.corrcoef(scaled.to_numpy().T)[0, 1])
        spearman = float(np.corrcoef(pairs.rank(method="average").to_numpy().T)[0, 1])
    return {
        "source": str(path.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_checkpoint": "2026-10-12 saved baseline; not a new current-date forecast",
        "rows": len(data), "finite_pairs": len(pairs), "excluded_nonfinite": int((~finite).sum()),
        "distinct_values": {c: int(pairs[c].nunique()) for c in pairs},
        "exact_zero_forecasts": int(pairs["Forecasted Demand"].eq(0).sum()),
        "pearson_r": pearson, "spearman_rho": spearman,
        "status": "Computable" if variable else "Inconclusive: insufficient pairs or a constant criterion",
        "interpretation": "Undefined correlation is not evidence of independence. This is a pre-eligibility input diagnostic, not a complete three-criterion ranking validation."
    }


def main():
    result = {"assessment_date": "2026-10-20", "baselines": [
        diagnose(ROOT / "validation_outputs/five_criterion_mca" / name)
        for name in ("mca_audit.csv", "uploaded_stock_mca_audit.csv")
    ]}
    output = ROOT / "validation_outputs/mca_criterion_review"
    output.mkdir(parents=True, exist_ok=True)
    (output / "correlation_summary.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
