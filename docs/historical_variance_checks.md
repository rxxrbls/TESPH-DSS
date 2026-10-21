# Historical-period mechanics checks — October 21, 2026

Equal weights (1/3 each) are the approved baseline. The limited April historical baseline may be reported with its limitations. The TA accepted these historical checks for final model sign-off on October 21, 2026; no additional historical return data is required. This document records technical results, not an approval request or a Member 3 handoff.

## Scope

Expanded the assessment to four predeclared consecutive earlier month ends within the available history: December 2025 through March 2026. Every result is retained. No new sales after April 24, 2026 were available or invented. Criteria, normalization, matching rules, models and eligibility safeguards were unchanged.

For each run, sales and return-request creation dates were restricted to the endpoint; forecasting history ended at that endpoint and forecasts began the next day. The corrected September catalog was retained as a fixed retrospective identity filter. It is not evidence that these products or stock levels were available at the historical endpoint. October-exported statuses are retrospective outcomes, not reconstructed information available on the original assessment date. No resulting stock-risk or replenishment outputs are published as historical recommendations.

## Results

| Endpoint | Eligible MCA products | Forecasts > 0 | Forecast criterion >= 0.01 units | Pearson | Spearman | Rank changes vs Sales Velocity alone |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-12-31 | 56 | 3 | 3 | 0.8707 | 0.4573 | 11 |
| 2026-01-31 | 56 | 8 | 8 | 0.7660 | 0.8473 | 6 |
| 2026-02-28 | 56 | 7 | 5 | 0.7058 | 0.7940 | 6 |
| 2026-03-31 | 57 | 1 | 0 | 0.6225* | 0.3136* | 0 |

Correlations compare Sales Velocity with Forecasted Demand across all eligible products, including zeros. The 0.01-unit column is a magnitude diagnostic, not a new scoring threshold. No values were rounded or excluded to obtain a preferred result.

*March's maximum forecast criterion is approximately 1.26e-25 units. Its mathematically nonzero variance and computable correlation do not establish practically meaningful demand variation; do not use this period as evidence that the demand criterion has become informative. Min-Max normalization can amplify very small differences; the unchanged rules were retained and this limitation is reported explicitly.*

The December–February runs contain non-negligible forecast variation, permitting correlation checks and demonstrating changes in ranking relative to Sales Velocity alone. Rank changes demonstrate formula mechanics, not improved business decisions or forecasting effectiveness.

Recorded Return/Refund Quantity Rate remains zero for every eligible product in every run. Equal thirds and 25/25/50 therefore produce **zero ordinal rank or priority-group changes** in every period. This is expected: both scenarios weight the two varying volume criteria equally relative to each other, while the return criterion contributes the same constant to every product. It does not establish insensitivity when refund rates vary.

## Remaining limitation

These runs provide additional real-data evidence for the two varying criteria. They do not demonstrate three varying criteria or reconstruct historical status availability. The TA accepted the remaining return-mapping/coverage limitation for reporting. Current baseline weights remain equal thirds; no automatic methodology or population change was made to force nonzero refunds.

Reproduce with `python qa/check_historical_variance.py` after the private corrected-data prerequisites are prepared. Evidence, source hashes, every assessment and both weight-scenario CSVs are in `validation_outputs/historical_variance/`. Request-level private records are not written to the public evidence directory.
