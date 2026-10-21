# Verification status — October 21, 2026

Member 2 integration candidate. TA historical validation is accepted; actual merged-build/demo acceptance remains required.

- Governed prepared data: 226,203 rows. The configured operational runtime database is absent locally; older 7,454/16,926 counts are not current candidate counts.
- Separate corrected full-schema CSV/database: 226,203 rows, 76 columns, all prepared/Star Schema values and row order reconciled, allowing SQLite numeric storage representation.
- Source-backed corrections: 112 SKU references across six products; two additional products become eligible. No invented SKU or relaxed ambiguity rule.
- Corrected candidate: 67 accepted products, 62 forecast-eligible products, 61 MCA rankings. The original working baseline remains unchanged.
- Regression: 432 tests passed after final approval and the synthetic staging test, including identifier preservation and baseline/comparison status distinction; one existing date-parsing warning. Evidence: `validation_outputs/integration_readiness/pytest_final_approval.txt`.
- Independent calculations: 62 forecasts, 186 metric rows, 62 sales velocities, 67 refund denominators, and both 61-product MCA scenarios passed.
- Current MCA page component: five checks passed for actual candidate tables, including backend equality, N/A and provisional labels. This is not a combined-build browser acceptance test.

Evidence: `validation_outputs/integration_readiness/` and `validation_outputs/sku_recovery/`.

Forecasted demand and counted refund rate remain zero across the eligible MCA dataset. Correlation is undefined and both weight scenarios yield identical ranks. These results support tested calculation behavior, not demonstrated improvement over Sales Velocity alone.

Latest technical decision: equal-third weights are the approved baseline; the limited historical baseline may be reported in Chapter 4 with its zero-variance and coverage limitations. Four earlier-period correlation/sensitivity runs are now complete; see [historical checks](historical_variance_checks.md). December–February have non-negligible forecast variation, but return rates remain constant and March is practically near zero. The TA accepted these limitations and historical validation for final model sign-off. No additional historical return data is required. No merged-build/demo-machine validation, deployment or Member 3 handoff has been completed.

Eight-SKU synthetic staging passed: refund rates 5?40%, independent cost-normalization/score checks, persisted SQLite outputs, repeat refresh, production page and actual CSV payload equality. See [synthetic evidence](synthetic_mca_validation.md).
