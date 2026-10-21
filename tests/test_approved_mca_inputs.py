import numpy as np
import pandas as pd
import pytest

from mca_inputs import calculate_profit_margin, calculate_stock_out_frequency, calculate_return_rate
from prescriptive_calculations import calculate_mca_scores
from prescriptive_pipeline import run_prescriptive_pipeline
from methodology_config import MCA_CRITERIA
from test_week3_prescriptive_pipeline import _pipeline_inputs


PERIOD = dict(period_start="2026-09-01", period_end="2026-09-02")


def financial():
    return pd.DataFrame({"SKU": ["SKU-A", "SKU-B"], "Date": ["2026-09-01", "2026-09-02"],
                         "Net Product Sales": [400, 1000], "Net Units Sold": [4, 10], "Unit Cost": [50, 20]})


def stock_history():
    return pd.DataFrame({"SKU": ["SKU-A", "SKU-A", "SKU-B", "SKU-B"],
                         "Date": ["2026-09-01", "2026-09-02"] * 2, "Net Sellable Stock": [0, 2, 3, 4]})


def test_profit_margin_reconciles_returns_and_effective_line_costs():
    data = pd.DataFrame({"SKU": ["A"] * 3, "Date": ["2026-09-01"] * 3,
                         "Net Product Sales": [100, 200, -50], "Net Units Sold": [2, 4, -1], "Unit Cost": [20, 30, 20]})
    row = calculate_profit_margin(data, **PERIOD).iloc[0]
    assert row.COGS == 140
    assert row["Net Product Sales"] == 250
    assert row["Profit Margin"] == 44
    missing = data.copy()
    missing.loc[0, "Unit Cost"] = np.nan
    assert np.isnan(calculate_profit_margin(missing, **PERIOD)["Profit Margin"].iloc[0])
    assert np.isnan(calculate_profit_margin(data.assign(**{"Net Product Sales": 0}), **PERIOD)["Profit Margin"].iloc[0])


def test_stock_days_do_not_impute_gaps_or_count_events():
    data = pd.DataFrame({"SKU": ["A"] * 5, "Date": ["2026-09-01", "2026-09-02", "2026-09-05", "2026-09-06", "2026-09-07"],
                         "Net Sellable Stock": [0, -1, 4, np.nan, np.inf]})
    row = calculate_stock_out_frequency(data, period_start="2026-09-01", period_end="2026-09-07").iloc[0]
    assert row["Valid Observed Days"] == 3
    assert row["Invalid Stock Days"] == 2
    assert row["Stock-Out Frequency"] == pytest.approx(200 / 3)
    assert np.isnan(calculate_stock_out_frequency(data.iloc[:1], **PERIOD)["Stock-Out Frequency"].iloc[0])
    with pytest.raises(ValueError, match="SKU-day"):
        calculate_stock_out_frequency(pd.concat([data, data.iloc[:1]]), **PERIOD)


def test_return_rate_uses_units_percentage_and_invalid_denominators():
    result = calculate_return_rate(pd.Series([1, 0, 3, np.nan]), pd.Series([5, 0, 2, 5]))
    assert result.iloc[0] == 20
    assert result.iloc[1:].isna().all()


def test_complete_approved_inputs_flow_and_missing_sku_exclusion():
    tx, analytics, forecast, stock = _pipeline_inputs()
    stock["Supplier Lead Time"] = [5., 7.]
    kwargs = dict(as_of="2026-09-28", mca_financial_lines=financial(),
                  mca_period_start=PERIOD["period_start"], mca_period_end=PERIOD["period_end"])
    result = run_prescriptive_pipeline(tx, analytics, forecast, stock, **kwargs)
    scores = result["mca_results"].set_index("SKU")
    assert set(scores.index) == {"SKU-A", "SKU-B"}
    assert scores.loc["SKU-A", "Profit Margin"] == 50
    assert scores.loc["SKU-B", "Profit Margin"] == 80
    assert "Stock-Out Frequency" not in scores
    assert "Stock-Out Frequency" not in result["mca_audit"]
    assert scores.loc["SKU-A", "Return Rate"] == 20
    assert scores.loc["SKU-B", "SKU Priority Score"] == pytest.approx(4 / 5)
    assert scores.loc["SKU-B", "Priority Rank"] == 1
    assert "Gross Revenue" not in scores and "Projected Stock-Out Risk" not in scores
    kwargs["mca_financial_lines"] = financial().iloc[:1]
    partial = run_prescriptive_pipeline(tx, analytics, forecast, stock, **kwargs)
    assert partial["mca_results"].SKU.tolist() == ["SKU-A"]
    assert partial["mca_results"]["SKU Priority Score"].iloc[0] == pytest.approx(.5)
    assert partial["mca_results"]["Priority Level"].iloc[0] == "High"
    assert partial["mca_audit"].set_index("SKU").loc["SKU-B", "MCA Status"] == "Unavailable: Profit Margin"


def test_replenishment_fallback_does_not_implicitly_become_mca_evidence():
    tx, analytics, forecast, stock = _pipeline_inputs()
    kwargs = dict(as_of="2026-09-28", mca_financial_lines=financial(),
                  mca_period_start=PERIOD["period_start"], mca_period_end=PERIOD["period_end"])
    result = run_prescriptive_pipeline(tx, analytics, forecast, stock, **kwargs)
    assert result["mca_results"].empty
    assert result["risk_results"]["Supplier Lead Time"].eq(7).all()
    explicit = run_prescriptive_pipeline(tx, analytics, forecast, stock, mca_use_lead_time_fallback=True, **kwargs)
    assert len(explicit["mca_results"]) == 2


def test_min_max_does_not_treat_distinct_small_values_as_equal():
    values = pd.DataFrame({"SKU": ["A", "B"], **{c: [1e-10, 2e-10] for c in MCA_CRITERIA}})
    result = calculate_mca_scores(values, identifier_columns=["SKU"]).set_index("SKU")
    assert result.loc["A", "Normalized Sales Velocity"] == 0
    assert result.loc["B", "Normalized Sales Velocity"] == 1


def test_previous_substitute_scores_are_invalidated_on_session_initialization(monkeypatch):
    import utils.state as state
    values = {"mca_results": pd.DataFrame({"SKU": ["A"], "Gross Revenue": [100]}),
              "recommendation_results": pd.DataFrame({"SKU": ["A"]})}
    monkeypatch.setattr(state.st, "session_state", values)
    state.initialize_app_state()
    assert values["mca_results"] is None
    assert values["recommendation_results"] is None
    assert "methodology was updated" in values["prescriptive_error_message"]


@pytest.mark.parametrize("key", ["mca_results", "mca_audit", "recommendation_results"])
def test_six_criterion_state_invalidates_scores_and_dependents(monkeypatch, key):
    import utils.state as state
    # Even an empty prior audit has a six-criterion schema and must be removed.
    values = {key: pd.DataFrame(columns=["SKU", "Stock-Out Frequency"]),
              "risk_results": pd.DataFrame({"SKU": ["A"]})}
    risk = values["risk_results"]
    monkeypatch.setattr(state.st, "session_state", values)
    state.initialize_app_state()
    assert all(values[k] is None for k in ("mca_results", "mca_audit", "recommendation_results"))
    assert values["risk_results"] is risk


def test_stock_history_has_no_effect_on_active_five_criterion_outputs():
    tx, analytics, forecast, stock = _pipeline_inputs()
    stock["Supplier Lead Time"] = [5., 7.]
    kwargs = dict(as_of="2026-09-28", mca_financial_lines=financial(),
                  mca_period_start=PERIOD["period_start"], mca_period_end=PERIOD["period_end"])
    baseline = run_prescriptive_pipeline(tx, analytics, forecast, stock, **kwargs)
    # Even unusable legacy history must not gate or alter current scores/risk.
    legacy = run_prescriptive_pipeline(tx, analytics, forecast, stock,
                                      mca_stock_history=pd.DataFrame({"invalid": [None]}), **kwargs)
    for name in baseline:
        pd.testing.assert_frame_equal(baseline[name], legacy[name])


@pytest.mark.parametrize("complete", [True, False])
def test_five_criterion_frontend_displays_backend_scores_and_downloads(complete):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from utils.state import DEFAULT_STATE, DataStatus
    tx, analytics, forecast, stock = _pipeline_inputs()
    stock["Supplier Lead Time"] = [5., 7.]
    result = run_prescriptive_pipeline(tx, analytics, forecast, stock, as_of="2026-09-28",
        mca_financial_lines=financial() if complete else None, mca_period_start=PERIOD["period_start"],
        mca_period_end=PERIOD["period_end"])
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "pages/product_prioritization.py")
    values = {**DEFAULT_STATE, "authenticated": True, "data_status": DataStatus.DATA_READY.value,
              "active_dataset_id": "fixture", "forecast_dataset_id": "fixture",
              "analytics_dataset_id": "fixture", "prepared_transactions": tx,
              "analytics_results": analytics, "forecast_results": forecast, **result}
    for key, value in values.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    audit_table = next(table for table in app.dataframe if "MCA Status" in table.value)
    expected_audit = result["mca_audit"].copy()
    for criterion in MCA_CRITERIA:
        expected_audit[criterion] = expected_audit[criterion].map(
            lambda value: "N/A" if pd.isna(value) else format(value, ".6g"))
    pd.testing.assert_frame_equal(audit_table.value, expected_audit, check_dtype=False)
    assert "Stock-Out Frequency" not in audit_table.value
    downloads = {button.label for button in app.get("download_button")}
    if complete:
        shown = next(table.value for table in app.dataframe if "SKU Priority Score" in table.value)
        pd.testing.assert_frame_equal(shown, result["mca_results"], check_dtype=False)
        assert downloads == {"Download MCA rankings", "Download MCA readiness audit"}
    else:
        assert audit_table.value["Profit Margin"].eq("N/A").all()
        assert downloads == {"Download MCA readiness audit"}
    assert any("20%" in caption.value and "five criteria" in caption.value for caption in app.caption)
