"""Independent integration checks for the real Week 2 forecast run."""

import numpy as np
import pandas as pd

from forecasting_pipeline import run_forecasting_pipeline


def verify(results):
    output = results["forecast_output"]
    detail = results["validation_detail"]
    metrics = results["validation_metrics"]
    if output.empty:
        raise AssertionError("No eligible forecasts; inspect eligibility and catalog evidence")
    assert not output.duplicated(["SKU", "Time"]).any()
    assert np.isfinite(output["Forecast"]).all() and output["Forecast"].ge(0).all()
    assert (detail["Time"] > detail["Origin"]).all()
    eligible = results["eligibility"].loc[lambda f: f.Eligible]
    assert set(output.SKU) == set(eligible.SKU)
    coverage = pd.Timestamp(results["selection_status"].iloc[0]["History Coverage End"])
    assert output.Time.min() > coverage
    config = results["methodology"].set_index("Parameter")["Value"]
    assert output.groupby("SKU").size().eq(int(config["horizon"])).all()
    for sku, group in detail.groupby("SKU"):
        method_dates = [set(zip(g.Origin, g.Time, g.Step)) for _, g in group.groupby("Method")]
        assert all(dates == method_dates[0] for dates in method_dates)
        for method, observations in group.groupby("Method"):
            actual = observations.Actual.to_numpy()
            errors = actual - observations.Forecast.to_numpy()
            row = metrics.loc[metrics.SKU.eq(sku) & metrics.Method.eq(method)].iloc[0]
            assert np.isclose(row.MAE, np.abs(errors).mean())
            assert np.isclose(row.RMSE, np.sqrt(np.square(errors).mean()))
            assert row["Validation Observations"] == len(actual)
            assert row["Zero Actual Count"] == np.count_nonzero(actual == 0)
            if config["mape_zero_policy"] == "denominator_floor":
                expected = (np.abs(errors) / np.maximum(actual, float(config["mape_denominator_floor"]))).mean() * 100
                assert np.isclose(row.MAPE, expected)
        candidates = metrics.loc[metrics.SKU.eq(sku)]
        expected_method = candidates.sort_values(["MAPE", "RMSE", "Method"], kind="stable").iloc[0].Method
        assert output.loc[output.SKU.eq(sku), "Method"].eq(expected_method).all()
    for name, keys in (("product_forecast", ["Product", "Category", "Time"]),
                       ("category_forecast", ["Category", "Time"])):
        expected = output.groupby(keys)["Forecast"].sum().sort_index()
        actual = results[name].set_index(keys)["Forecast"].sort_index()
        pd.testing.assert_series_equal(actual, expected)
    return {"forecast_skus": output.SKU.nunique(), "forecast_rows": len(output),
            "validation_rows": len(detail), "coverage_end": str(coverage.date()),
            "forecast_end": str(output.Time.max().date())}


if __name__ == "__main__":
    result = run_forecasting_pipeline()
    print(verify(result))
    print(result["eligibility"]["Reason"].value_counts().to_string())
    print(result["inventory_review"]["Reason"].value_counts().to_string())
    print("WEEK 2 FORECAST VERIFICATION: PASS")
