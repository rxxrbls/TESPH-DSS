> Current policy update (October 21): equal-third baseline weights and reporting the historical baseline with its limitations are approved. Expanded-period checks and final validation remain required. Earlier pending-weight statements below describe the previous checkpoint. This is still a backup branch, not an issued handoff.

# Corrected SKU candidate: integration handoff

> **Draft only.** Retained as future integration reference. The user has not issued a handoff to Member 3; `sab-week3` is currently a backup checkpoint.

October 21, 2026. This is a provisional integration candidate, not a deployed or finally approved assessment.

## Package and data

Use `tesph_sku_corrected_readiness_candidate.zip` and its `readiness_manifest.json` / package receipt. Preserve the previous working checkout and databases. This package supplements the existing technical flow documentation in `three_criterion_implementation_results.md`; use the three-criterion path, not historical five/six-criterion requirements.

The source archive excludes private datasets and credentials. Authorized corrected data is under `.artifacts/qa/integration_readiness/`:

- `prepared_transactions.csv`: full 76-column, 226,203-row corrected handoff.
- Six Star Schema CSVs: matching fact and dimension tables.
- `corrected_candidate.db`: matching runtime snapshot, with 226,203 prepared and fact-sales rows.

Do not use `.artifacts/qa/sku_recovery/source_exact_candidate.csv` as the full ETL handoff: that earlier investigation file contains only the analytics-required subset of columns. Do not use `incremental_seed.db` as the full dataset.

In a fresh integration checkout, provide the corrected prepared/Star Schema CSVs as one coherent `final_outputs` set. Supply the unchanged authorized stock files and cleaned return/refund archive separately. Preserve other required governed files. For a prepared runtime start, supply a copy of `corrected_candidate.db` at the configured `runtime_data/active_transactions.db` path in that isolated checkout. Do not replace an existing operational runtime with uploads that have not been reconciled.

The candidate database contains transaction state, not an activated three-criterion return-review store. Upload/refresh current stock and the cleaned return/refund evidence with the explicit documented dates to recompute connected outputs and activate the three-criterion workflow. No old session or return-review DB should be treated as evidence for a different dataset.

Verify the hashes in `validation_outputs/integration_readiness/summary.json`. The original governed prepared hash starts `66b3aa57`; the corrected prepared hash is `e4e6ce36bdfcdb59b4bfe4f136429c703755d63d0152b327b6ebcda94682e4b2`. They intentionally differ.

## Functions and rules to preserve

- `etl.extract_file`, `transform_transactions`: current upload schema and identifier preservation.
- `runtime_data_store`: duplicate/correction handling, dataset identity and atomic runtime publication. Re-uploading raw records is not a migration for the old prepared SKU labels; use the reviewed corrected baseline for this candidate.
- `active_inventory` / inventory crosswalk: unique exact identities, duplicate-SKU and stock-pool exclusions.
- `sku_forecasting` and forecasting calculations: common chronological holdouts, approved demand/status definition and model-selection rules.
- `three_criterion_mca`: three criteria, missing-value exclusion, constant normalization of 0.5, provisional weight scenarios and selected-request-date interpretation.
- `return_refund_store` / `mca_refresh`: persistent request review, per-batch dispute re-evaluation, rollback and audit history.
- Page/shared-state invalidation: invalidate outputs when dataset authority changes; preserve N/A and provisional labels.

Do not run legacy `etl.py` standalone cleaning or `final_etl_handoff.py` regeneration as startup steps. This work restores verified historical identifiers in an isolated full-schema candidate; it does not rewrite or certify the older standalone preparation path.

## Reproduction

Install dependencies using the existing setup guide and the ZIP's `tested-environment.txt`. From the repository root:

```text
python -m pytest tests -q
python qa/verify_integration_readiness.py
python qa/check_corrected_mca_page.py
```

The readiness script requires the authorized original governed data, existing full QA seed, return/refund archive and SKU investigation artifacts. It reproduces the isolated candidate rather than modifying an operational runtime. If rebuilding those prerequisites, follow the SKU recovery report and benchmark seed preparation instructions first.

The current evidence covers 428 existing tests plus two added preservation tests. A fresh combined run should collect 430 tests if Member 3 makes no test changes.

## Combined-build acceptance still required

Record commit/source snapshot, configuration and data hashes. Check actual uploads, repeat uploads, stock refresh, return/refund refresh and dispute audit events, page navigation, downloads, sign-in, and the intended demo computer.

With the same raw stock upload and documented historical policy, expect 67 accepted catalog products, 62 forecast SKUs, 61 provisional MCA scores and one unscored forecast SKU. Using the older governed stock mapping can produce different counts; identify the stock source instead of treating those results as equivalent.

Check backend/screen/CSV equality, missing-value display and prior-session invalidation. New data or mapping changes require new expected counts and recalculation. Final weights and baseline acceptance remain pending TA direction.
