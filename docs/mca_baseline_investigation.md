# MCA baseline investigation

Date: October 20, 2026. Scope: read-only investigation of source records, catalog eligibility, request matching and the actual forecasting pipeline. No production eligibility rules, demand definitions, weights or data were changed.

## Conclusion

Do not conclude from this baseline that three-criterion MCA is inherently unsuitable. The baseline is strongly restricted by the real-SKU eligibility rule, and its final demand window contains orders whose recorded statuses have not reached the existing demand definition.

Keep the three-criterion implementation provisional while the TA reviews the unit of analysis and the handling of incomplete order outcomes. Do not switch to Sales Velocity alone merely because this restricted baseline is constant. This investigation does not establish that an expanded population would make MCA effective; that still requires evaluation.

## 1. Missing SKUs exclude most of the available business records

The prepared sales dataset has 226,203 rows and 2,116 historical product keys. Of those sales rows, 225,370 have no recorded SKU. There are 2,021 product keys with no recorded historical SKU.

The current-stock workbook has 1,980 rows. Its crosswalk identifies 1,092 unambiguous stock-to-history candidates, 834 unmatched rows and 54 requiring review. Of the 1,092 candidates, 1,025 have no SKU.

The subsequent active-catalog gate reports these mutually exclusive first-failure reasons:

| Gate result | Stock rows |
| --- | ---: |
| Missing source SKU | 1,712 |
| Missing or duplicate product key | 111 |
| Reused SKU / unresolved stock pool | 90 |
| Historical/current SKU conflict | 2 |
| Eligible current-catalog match | 65 |

Of the 65 accepted identities, 60 have sufficient forecast history. Of those 60, 59 have a positive MCA eligible-order denominator. These are different stages, not contradictory SKU counts.

Original-export spot checks support the source-data explanation: August 2022 has 7,334 rows but only three nonblank SKU references; March 2026 has 28 rows and 14 nonblank SKU references; April 2026 has 86 rows and 15 nonblank SKU references. These checks do not constitute an exhaustive raw-file reconciliation of all months.

## 2. Refund data overlaps with stock candidates, but not with the eligible SKU subset

There are 2,224 return/refund item lines matching unambiguous stock-to-history candidate keys, including 1,273 Request Refunded lines. However, only one request line matches the 65 accepted SKU identities, and it is cancelled.

Therefore, the earlier phrase “only one request matches the current catalog” needs qualification: it means the **eligible SKU population**, not all products in the stock workbook. The existence of other product-level overlaps is evidence for reviewing identity eligibility, not permission to bypass it.

Searching the full history for one-to-one nonblank source SKUs does not by itself solve this: the diagnostic finds 93 such historical identities, none with positive eligible demand in the final 30 days.

## 3. Zero forecasts are consistent with the supplied demand inputs

The latest positive demand date among accepted catalog identities is March 13, 2026, 42 days before the April 24 endpoint. All have zero eligible demand in the final 30 days. One accepted identity has no positive eligible-demand history at all.

The independent rerun produced 420 daily forecast rows, all exactly zero, using 30 Exponential Smoothing selections, 19 Linear Regression selections and 11 Moving Average selections. The forecast-history endpoint is April 24, not October 20. All 17,430 rolling-validation actual observations are zero. This explains why the baseline is not a meaningful active-demand accuracy demonstration.

No display-rounding explanation or inadvertent extension of the forecast calendar to today's date was found. The model implementations use the supplied demand series, including zero-filled dates and nonnegative regression predictions.

## 4. Zero eligible demand does not mean no recorded order activity

In the original April export:

| Recorded status | Rows |
| --- | ---: |
| Completed | 2 |
| Cancelled | 22 |
| Shipping | 20 |
| Delivered | 19 |
| Order received, with a future return/refund deadline | 19 |
| To ship | 4 |

The current Completed/Returned demand definition gives positive demand to only two April rows. There are 62 noncancelled April rows with zero demand under that definition.

Within the 65 accepted catalog identities, April contains 15 rows: seven Delivered, four Shipping, two Cancelled, one order received with a return deadline, and one To ship. None contributes positive eligible demand under the current rules.

This is a status-snapshot limitation. Do not reinterpret these rows automatically as completed sales, cancellations, or proof of zero buyer demand. An old order date also does not prove that its recorded status was later refreshed: the August 2022 sample still contains 137 Order Received rows.

## 5. Period selection alone is not a complete solution

A fixed sequence of recent endpoints was examined without selecting dates to obtain favorable rankings:

| Endpoint | Accepted current-catalog identities with positive demand in preceding 30 days | All historical products with positive demand in preceding 30 days |
| --- | ---: | ---: |
| December 31, 2025 | 3 | 13 |
| January 31, 2026 | 8 | 22 |
| February 28, 2026 | 12 | 36 |
| March 31, 2026 | 11 | 20 |
| April 24, 2026 | 0 | 2 |

These are activity diagnostics, not alternative validated forecasts or MCA rankings. The September stock catalog is retrospective relative to these dates; it cannot establish which products were active at each historical date. Moving the endpoint also does not recover the refund-bearing products excluded for missing SKUs.

## Recommended TA direction

Before changing the number of criteria, ask whether the study may use the existing internal product-variation key as its analysis identifier for unambiguous product/variation matches when seller SKUs are blank. Preserve unmatched, conflicting and pooled-stock exclusions. A product key must be labeled as an internal identifier, never relabeled as an actual seller SKU.

Also agree how to handle status snapshots and the assessment endpoint. Possible directions include retaining a clearly defined completed/returned-order estimand with its limitations, obtaining updated outcomes where available, or revising the demand/observation policy with explicit justification. Merely moving dates or counting Delivered/Shipping as Completed is not an automatic fix.

If those directions are approved, rerun coverage, request review, forecasting validation and both weight scenarios on the justified population. Evaluate usefulness against the Sales-Velocity-only baseline before claiming an improvement.

## Reproduction and evidence

Run `python qa/investigate_mca_baseline.py` in the project environment. It reads the existing governed transactions, raw stock workbook, isolated full-seed product dimension and supplied return/refund ZIP.

Evidence is in `validation_outputs/mca_investigation/`: `summary.json`, `raw_export_checks.json`, `current_catalog_history.csv`, `stock_exclusion_counts.csv`, `forecast_eligibility_counts.csv`, `current_selected_methods.csv`, `current_forecasts.csv`, and `unique_historical_sku_history.csv`.

The earlier integration package remains the tested provisional implementation. This investigation is an additional methodological finding, not an approved policy change or a new final-ranking claim.
