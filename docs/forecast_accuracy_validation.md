# Forecast Method Accuracy final validation — 2026-10-08

The Demand Forecast section is implemented and locally validated against the current ETL handoff and repository Streamlit frontend. This report covers the current checkout, not a deployed copy of the earlier screenshot. The screenshot's exact ten-SKU selection and session inputs were not available for reproduction.

## Findings and fixes

- Metrics are calculated from expanding-window, out-of-sample predictions. They are not placeholder zeros. Parameters are tuned inside each training split, with no access to the outer holdout; final production parameters are then retuned on available history.
- The actual-data run contains 59 forecasted SKUs and 177 candidate metric rows. Every holdout actual is zero. Consequently all 177 R² values are mathematically undefined, including Linear Regression. Raw MAPE is also undefined; the configured adjusted MAPE remains available.
- 138 MAE values are exactly zero; another 30 are positive but below 0.005 and would appear as `0.00` with two decimal places. The page now uses scientific notation for small nonzero scores, explicit `N/A` for unavailable/nonfinite scores, and an explanation for undefined R². It does not replace missing values with zero.
- R² previously used an absolute near-zero tolerance for total variance, incorrectly rejecting some varying, small-scale actuals. It now distinguishes zero variance from small positive variance. Regression coverage verifies the correction.
- Validation now rejects mismatched forecast/holdout calendars instead of pairing them by row position silently.
- The page displays each SKU/method separately, selected status, observation counts, zero counts, adjusted/raw MAPE labels, and R² applicability. It exposes actual-versus-predicted comparisons by training cutoff and downloadable full-precision metrics and observations. No average of unrelated SKU R² scores is presented as a model score.

## Methodology verified

Authority is the existing [Week 2 handoff](week2_handoff.md) and [current methodology](prescriptive_methodology.md). TA constraints and team-selected operating parameters remain distinguished; this work does not claim a new TA sign-off.

| Item | Applied rule |
| --- | --- |
| Scope | Eligible SKU with active/current-catalog or explicit client-approved mapping; product/category forecasts sum SKU predictions |
| Demand | Completed or returned/refunded gross demand; retain covered zero-demand days |
| Operating horizon | Daily history; seven future days |
| Validation | Up to 14 expanding origins, seven forecast steps each; minimum 37 training days |
| Moving average tuning | Feasible windows from 3/7/14/30 days; adjusted MAPE, RMSE, smaller window for exact ties |
| Exponential smoothing tuning | Alpha 0.1–0.9; RMSE/SSE, then MAE, then smaller alpha |
| Final method | Unrounded adjusted MAPE, then RMSE, then method name for exact ties |
| MAE / RMSE | Mean absolute error / square root of mean squared error, in demand units |
| Adjusted MAPE | `100 × mean(abs(actual − forecast) / max(abs(actual), 1))`; denominator floor is documented team configuration |
| Raw MAPE | Undefined if any actual is zero |
| R² | `1 − SSE/SST`; undefined for fewer than two observations or constant actuals; negative values permitted |

Each origin/step has equal weight. Overlapping horizons repeat target dates at different origins. Method-selection scores are not an independent evaluation of the selected winner.

## Actual-data evidence

Full regression command: `.venv/Scripts/python.exe -m pytest -q` — **390 passed**, one existing pandas date-inference warning, in 91.20 seconds. Focused forecasting/frontend checks also passed (67 tests). After adding an exact constant-array guard for fractional actuals in R², the affected forecasting/display suites passed again (66 tests). The real-data audit completed with process exit 0.

Run `.venv/Scripts/python.exe validate_forecast_accuracy.py` from the repository root. The audit uses the immutable prepared transaction handoff and the actual current-stock catalog, with a reproducible catalog assessment date of 2026-10-08. It writes evidence under [validation_outputs/forecast_accuracy](../validation_outputs/forecast_accuracy/summary.json).

| Evidence | Result |
| --- | --- |
| Prepared transaction rows | 226,203 |
| Latest sales coverage | 2026-04-24 |
| SKU/method metric rows | 177 |
| Origin/step/method observations | 17,136 |
| Forecasted SKUs / future rows | 59 / 413 |
| Selected Exponential Smoothing / Linear Regression / Moving Average | 30 / 19 / 10 |
| Holdout dates across all observations | 2026-04-05 through 2026-04-24 |
| Constant-zero-actual SKUs | 59 |

The audit independently recalculates MAE, RMSE, adjusted MAPE and R²; checks raw MAPE and observation counts; reconciles demand to prepared source quantities and status flags; verifies identical candidate holdout coverage, temporal ordering, unrounded method selection and propagation into future forecast rows; and renders the actual Demand Forecast page using Streamlit AppTest, comparing its accuracy table with the backend-derived table. The summary records the source CSV SHA-256 for reproducibility.

Evidence files include `validation_metrics.csv`, `validation_detail.csv`, `best_methods.csv`, `forecast_output.csv`, `frontend_accuracy.csv`, `methodology.csv`, and `summary.json`. Blank numeric cells in machine-readable CSV files mean undefined, not zero; the frontend shows N/A.

## Interpretation for Chapter 4 and integration

The zero/near-zero errors describe a no-demand validation window and must not be presented as evidence of excellent forecasting during active sales. R² cannot be made meaningful by changing its display or by choosing Linear Regression. A further evaluation containing varying actual demand would be needed to support that claim. The page now explicitly explains this condition.

Sales coverage ends in April despite the September current-stock snapshot. Stock recency does not extend sales coverage. Forecasts are historical, and the page states that current sales data is needed for current inventory decisions.

The local page's data binding is verified with Streamlit AppTest. Deployment, a separate frontend branch, and human visual acceptance in the team's browser are outside this run. The earlier screenshot is consistent with the verified rounding and constant-actual explanations, but cannot be attributed to an exact historical session without its inputs.
