> Current policy update (October 21): equal-third baseline weights and reporting the historical baseline with its limitations are approved. Expanded-period checks and final validation remain required. Earlier pending-weight statements below describe the previous checkpoint. This is still a backup branch, not an issued handoff.

# SKU mapping investigation and isolated recovery trial

Date: October 20, 2026

## Finding

Most missing SKUs were already absent in the original Shopee exports. However, two existing catalog products were excluded because processing collapsed spaces within their source SKU identifiers. Restoring their exact original identifiers in an isolated candidate recovered both products without changing the MCA methodology.

This improves coverage slightly. It does **not** resolve the baseline's zero forecast demand or zero counted return/refund rates.

## Original exports versus processed data

The audit read all 84 available order workbooks: 226,205 original rows and 226,203 prepared rows. Every prepared order/product/variation identity matched its original source workbook.

- Original rows with blank SKU: **225,372**.
- Prepared rows with blank SKU: **225,370**.
- Prepared blank SKUs whose matching original identity had a nonblank SKU: **0**.
- The order workbooks contain `SKU Reference No.` and `Parent SKU Reference No.` but no Product ID, Variation ID, Item ID or Model ID columns detected by the audit.
- The stock workbook has Product ID and Variation ID, but these cannot establish an ID-based join to order exports that lack those fields.
- Only three original order rows have a parent SKU. Their variant SKU is already populated; these do not recover missing variant identities.

The two-row difference between raw and prepared counts is not evidence of dropped SKU values. This investigation establishes SKU lineage for every retained prepared row; it does not newly certify every other ETL transformation.

## Confirmed recoverable processing differences

The separate candidate restores source values using the original workbook, Order ID, product and variation. It rejects ambiguous source matches. It does not generate identifiers, guess replacements or use fuzzy product matching.

| Prepared identifier | Exact original and catalog identifier | Transaction rows |
|---|---|---:|
| `BELOSNSCREEN-Set of 3pcs Belo` | `BELOSNSCREEN-Set of 3pcs  Belo` | 7 |
| `TrashBag-Large 10pcs / Roll` | `TrashBag-Large  10pcs / Roll` | 3 |

The original identifiers contain **two spaces** where the prepared identifiers contain one. Both original values agree with the existing current-stock catalog. Restoring them removes the historical/current SKU conflict.

There are also 100 numeric identifier differences:

- `0.0` → original `0`: 99 transaction rows, covering two tent variations.
- `130244.0` → original `130244`: one transaction row.

These exact source restorations are tested in the isolated candidate, but **do not make those products eligible**. Their SKUs are reused across stock rows, and the existing ambiguity safeguards remain in force. We did not merge their stock pools or select a preferred listing.

The literal audit also found two rows where `LICORISESERUM-1pc Licorise S` had collapsed spaces compared with original `LICORISESERUM-1pc  Licorise S`. This SKU is reused across stock listings, so the product remains excluded after restoration.

Total: **112 source references restored across six product keys; two additional products admitted.** The literal cross-check covered all **833 nonblank original SKU references** across 48 workbooks and found no ambiguous original identifiers among them.

## Before-and-after results

Both runs use the same sales, stock and return/refund sources, dates, forecasting rules, MCA criteria, weight scenarios, normalization and eligibility safeguards.

| Measure | Working baseline | Isolated candidate |
|---|---:|---:|
| Accepted current-catalog products | 65 | 67 |
| Sales rows in accepted mapping | 587 | 597 |
| Historical gross-demand units in accepted mapping | 738 | 751 |
| Forecast-eligible SKUs | 60 | 62 |
| Forecast output rows | 420 | 434 |
| Nonzero forecast rows | 0 | 0 |
| Return/refund lines in accepted mapping | 1 | 1 |
| Request Refunded lines in accepted mapping | 0 | 0 |
| Provisional MCA scores | 59 | 61 |
| Forecast-eligible SKUs excluded from MCA | 1 | 1 |

The one mapped return/refund request is cancelled. This does not mean the shop has no refunds: many refund records belong to products outside the accepted SKU subset.

All forecasts for previously eligible SKUs are exactly unchanged. Adding eligible products can affect MCA normalization bounds, scores and rank positions under the existing rules; it is not a change to those rules.

The two recovered products last appear in the sales records in November 2025 and January 2026. Their inclusion does not restore recent positive demand at the April 24, 2026 endpoint.

## Remaining limitation

The current stock workbook contains **1,712 rows without a SKU**. Of the unambiguous stock-to-history candidates, **1,025 have no stock SKU**; none has a nonblank historical SKU in the existing product dimension that could simply fill that gap.

Exact product-name/variation matching already establishes many product-level connections, but it does not supply the missing seller SKU. Parent SKUs, stock-only platform IDs and internal product keys have not been substituted for seller SKUs.

Other unresolved stock rows remain excluded under the existing duplicate-SKU and ambiguous-product rules. No evidence supports forcing them into the current eligible population.

## Preservation and verification

- Working-source checkpoint: `.artifacts/qa/sku_recovery/working_source_before_investigation.zip`, with a SHA-256 manifest.
- Original prepared transaction SHA-256 remains `66b3aa57d6bb4352e04399370ba602fd368e378994dbf6fe38d343480502917e`.
- Both audit and isolated comparison verify their input source and pre-existing working files were unchanged during execution.
- An additional comparison against the original checkpoint verified **90 pre-existing application and test files unchanged**.
- Candidate transaction data and mapping tables are under `.artifacts/qa/sku_recovery/`; they have not replaced the app's data.
- The full before/after analytics, forecasting and three-criterion prescriptive pipelines ran successfully using existing calculation modules.
- Inventory and three-criterion regression checks: **81 passed in 8.78 seconds**.
- Assertions verify unchanged non-SKU transaction fields, unchanged product keys and non-SKU dimension fields, and exact equality of existing-SKU forecasts.
- No production module, criteria, weights or normalization was changed. No browser acceptance of this candidate, production ETL regeneration, commit, push or merge is claimed.

## Reproduction and evidence

Run with the project's virtual environment:

```text
python qa/audit_sku_recovery.py
python qa/audit_literal_sku_identifiers.py
python qa/test_sku_source_restoration.py
python -m pytest tests/test_inventory.py tests/test_three_criterion_mca.py -q
```

Evidence directory: `validation_outputs/sku_recovery/`.

- `summary.json`: full original-workbook audit and blank-reference trial.
- `raw_file_inventory.json`: per-workbook row counts and identifier fields.
- `source_exact_changes.csv`: source-backed corrections.
- `restoration_comparison.json`: full before/after results and preservation checks.
- `before_*` and `after_*` CSVs: forecasts, MCA readiness, rankings and sensitivity outputs.
- `literal_identifier_audit.json`: literal source-identifier cross-check.
- `preservation_verification.json`: application/test-file hashes checked against the original checkpoint.

Private audit files include transaction identifiers and should remain in the authorized workspace.
