# Prescriptive Methodology and System Assumptions

These defaults are TESPH DSS operating assumptions. Shopee transaction exports
provide historical sales data; they do not establish current stock, stock age,
supplier lead time, review cadence, or a safety-stock policy. Current inventory
must be supplied and validated separately. These values are configurable in
`methodology_config.py` and are not represented as facts from the transaction
dataset.

## MCA

| Criterion | Direction | Weight |
| --- | --- | ---: |
| Sales Velocity | Benefit | 1/6 |
| Gross Revenue | Benefit | 1/6 |
| Supplier Lead Time | Cost | 1/6 |
| Projected Stock-Out Risk | Cost | 1/6 |
| Forecasted Demand | Benefit | 1/6 |
| Return Rate | Cost | 1/6 |

Equal weighting is the defensible baseline because there is no documented
stakeholder elicitation or empirical validation supporting unequal influence.
The prior 0.17/0.17/0.16/0.17/0.17/0.16 split implied precision without evidence.
Differential weights should be introduced only after a documented review.

Each criterion uses Min-Max normalization in its configured benefit/cost
direction. A constant criterion receives the neutral score 0.5. All six
criteria must be finite and present for an MCA score; missing criteria are not
imputed, and the affected SKU has no MCA rank. Scores sort descending, with
identifier columns ascending as deterministic tie-breakers. Priority bands are
High at scores of at least 2/3, Medium at least 1/3 and below 2/3, and Low below
1/3.

## TESPH DSS Defaults

| Assumption | Default and handling |
| --- | --- |
| Forecast horizon | 7 daily periods. |
| Default supplier lead time | 7 days; a system default, not a per-SKU Shopee field. |
| Review period | 7 days. |
| Safety stock | One day of mean forecast demand, rounded up to a whole unit. |
| Replenishment target | Mean daily forecast demand multiplied by lead time plus review period, rounded up, plus safety stock. The forecast rate is extended across the protection period if it exceeds the forecast horizon. |
| Maximum stock age | 90 days, inclusive; future-dated, stale, unmatched, invalid, or review-required stock is not used for risk, MCA, or recommendations. |
| DOI bands | Critical: DOI <= 1 day; High: 1 < DOI <= 3 days; Medium: 3 < DOI <= 7 days; Low: DOI > 7 days. |

Days of Inventory (DOI) is current stock divided by mean daily forecast demand.
Zero forecast demand is labeled `No Forecast Demand`; DOI is undefined. Risk
Index is the clipped share of forecast-horizon demand not covered by stock:
`max(forecast demand - current stock, 0) / forecast demand`, bounded to [0, 1].
It is an exposure measure, not a probability. With known stock and zero forecast
demand, Risk Index is 0 and DOI is not applicable. With missing stock, Risk
Index remains unavailable (NaN); the SKU is not imputed into the MCA. A missing
stock match is reported as `Insufficient Stock Data` when forecast demand is
positive.

## Configuration

Forecast horizon and DOI thresholds are in `methodology_config.py` as
`FORECAST_HORIZON` and `STOCK_RISK_THRESHOLDS`. Supplier lead time, review
period, safety-stock days, and maximum stock age are grouped in
`REPLENISHMENT_CONFIG`. Risk Index formula and its zero-demand/missing-stock
values are named in `RISK_INDEX_FORMULA`, `RISK_INDEX_ZERO_DEMAND_VALUE`, and
`RISK_INDEX_MISSING_STOCK_VALUE`. The calculation layer consumes these values
or accepts explicit parameters for scenario checks. Update the configuration
and this table together when TESPH DSS operating assumptions are formally
revised.