# Prescriptive Methodology and System Assumptions

Shopee transaction exports provide historical sales data; they do not establish current stock, stock age, or supplier lead time. Current inventory must be supplied and validated separately. Configurable system assumptions are documented in `methodology_config.py`.

> **Work in progress:** Equal-third baseline weights and reporting the historical baseline with its limitations are approved. Historical-period validation is accepted by the TA. This is an integration candidate; merged-build acceptance is still required.

## MCA

| Current criterion | Direction | Approved baseline | Sensitivity comparison only |
| --- | --- | ---: | ---: |
| Sales Velocity | Benefit | 1/3 | 25% |
| Forecasted Demand | Benefit | 1/3 | 25% |
| Recorded Return/Refund Quantity Rate | Cost | 1/3 | 50% |

The recorded quantity rate is eligible recorded refunded units divided by eligible ordered units, times 100, within explicit order and request-date windows. It does not claim physical returns or lifetime refund coverage. Unresolved relevant evidence, missing coverage or an invalid denominator makes the rate unavailable. Missing criteria exclude a product; they are not assigned zero or 0.5.

Each criterion uses Min-Max normalization over complete finite eligible products. A valid constant criterion receives 0.5. Ranking uses full precision with ascending SKU ties; High/Medium/Low groups use cumulative ceiling cutoffs of 25% and 75%. The displayed baseline uses approved equal thirds; historical validation is accepted; merged-build acceptance remains required. See [implementation and counting rules](three_criterion_implementation_results.md) and [coverage record](return_refund_coverage_record.md).

## Legacy five-criterion compatibility

Before return/refund evidence activates the three-criterion workflow, older callers retain the following policy. It is not the current three-criterion assessment:

| Legacy criterion | Direction | Weight |
| --- | --- | ---: |
| Sales Velocity | Benefit | 20% |
| Profit Margin | Benefit | 20% |
| Supplier Lead Time | Cost | 20% |
| Forecasted Demand | Benefit | 20% |
| Return Rate (units, percent) | Cost | 20% |

Profit Margin uses 100 times net product sales less COGS, divided by net product sales; COGS is net sold units times the applicable unit cost. Stock-Out Frequency was removed by the 2026-10-12 revision. Return Rate is returned units divided by gross units times 100 over the explicit MCA period. No revenue/risk substitutes are used.

Each criterion uses Min-Max normalization; an exactly constant criterion receives 0.5. Only complete, finite five-criterion SKUs enter normalization, ranking and percentile groups. Missing inputs remain unavailable. The approved tie rule is ascending SKU; priority groups are 25/50/25, with fractional cutoffs rounded up. Applying the replenishment lead-time fallback to MCA is an explicit separate choice and is disabled by default because the clarification document leaves that choice open.

## Approved TESPH DSS operating values

| Assumption | Value and handling |
| --- | --- |
| Forecast horizon | 7 daily periods. |
| Supplier lead time | Per-SKU value when available; otherwise a 7-day fallback labeled `Fallback 7-Day Default Used`. |
| Review period | 7 days. |
| Safety stock | One day of average forecast demand, rounded up to a whole unit. |
| Target stock level | Average daily forecast demand Ã— (lead time + review period), rounded up, plus safety stock. |
| Recommended quantity | `max(target stock level - current net sellable stock, 0)`. |
| Maximum stock age | 90 days, adjustable; future-dated, stale, unmatched, invalid, or review-required stock is excluded. |
| Stock definition | Operator confirms uploaded `Stock` is net sellable quantity (on-hand minus reserved/allocated). |
| Missing stock date | Latest transaction date may be used as an interim estimate when transaction dates exist; otherwise operator enters the actual date. |
| DOI bands | Critical: stock <= 0 with positive forecast; High: 0 < DOI <= lead time; Medium: lead time < DOI <= 1.5 Ã— lead time; Low: DOI > 1.5 Ã— lead time. No positive forecast demand is `No Forecast Demand`. |

Days of Inventory (DOI) is current net sellable stock divided by average daily forecast demand. Risk Index is the clipped share of forecast-horizon demand not covered by stock: `max(forecast demand - current stock, 0) / forecast demand`, bounded to [0, 1]. It is an exposure measure, not a probability. Zero forecast demand produces Risk Index 0 and undefined DOI. Missing stock remains unavailable rather than being imputed.

Forecast horizon and DOI thresholds are in `methodology_config.py` as `FORECAST_HORIZON` and `STOCK_RISK_THRESHOLDS`. The lead-time fallback, review period, safety-stock days, and maximum stock age are grouped in `REPLENISHMENT_CONFIG`. Update this document with approved changes to those values.
