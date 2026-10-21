# Integration QA results â€” 2026-10-10

> Historical 2026-10-10 checkpoint. For the current three-criterion workflow, use [current three-criterion implementation](three_criterion_implementation_results.md). Historical stock is no longer an active MCA requirement.


This report covers the current local `week3-integrated` candidate. The [current handoff](corrected_candidate_integration_handoff.md) records decisions and remaining inputs; the [setup guide](integration_candidate_setup.md) provides reproduction commands.

## Six closing tasks

| Task | Deliverable | Status |
| --- | --- | --- |
| 1. Consolidate the handoff | Current handoff and approval matrix supersede historical reports | Complete |
| 2. Measure representative uploads | Three isolated repeat, incremental and forecast trials; identity, totals and database checks | Passed all nine trials |
| 3. Fix verified bottlenecks | Stable-key generation, missing-value counting, fingerprint reuse, duplicate restore and temporary-frame release | Complete; 405 regression tests passed |
| 4. Exercise the integrated frontend | Actual app login, real uploads, forecast metrics, stock and prescriptive pages | All 12 browser checks passed; no browser errors; mobile header reviewed |
| 5. Prepare setup and candidate package | Source/data checksum manifest, dependency inventory and verified ZIP | Complete; ZIP integrity and all included-file checksums verified |
| 6. Record remaining inputs and acceptance | MCA ledger, stock history, period, fallback choice, combined-build acceptance | Requirements documented; external inputs remain |

## Regression and equivalence

The final suite passed **405 tests** in 101.06 seconds. Its one warning comes from the deliberate invalid-date case in `test_week2_alignment.py`; no test failed. `git diff --check` also passed. Full-dataset snapshot and dtype comparisons passed. The additional regression covers a text column whose later SQL chunks contain only nulls, preventing chunk boundaries from changing the restored dtype.

The subsequent narrow-screen CSS adjustment passed the five authentication/navigation tests (2.91 seconds) and is covered by the final browser run; backend code did not change after the full suite.

Evidence: `validation_outputs/integration_qa/pytest.txt` and `snapshot_equivalence.json` in the same directory.

The browser checks run the actual `app.py` with isolated runtime paths and generated local credentials. They verify rejected/accepted login, the real-data dashboard, full-precision forecast CSV equality with the independent audit, the no-demand explanation, invalid upload handling, zero-added-row XLSX repeat, the real stock workbook, connected risk/MCA-readiness/replenishment pages, and refresh restoring the login gate. The narrow-screen header was adjusted after visual review; desktop layout is unchanged. A 390Ã—844 viewport capture checks the header with navigation collapsed. This is viewport coverage in desktop Edge, not certification on a physical mobile browser.

All 12 checks passed with no browser errors. Results and screenshots are in `validation_outputs/integration_qa/browser/`. The source archive is `.artifacts/integration_candidate/tesph_integration_candidate.zip`; its separate receipt is `validation_outputs/integration_qa/package_receipt.json`. The archive includes the checksum manifest, tested dependency versions, setup guide and QA evidence. Governed/raw datasets, live databases and real credentials are supplied separately through the authorized data handoff.

## Measurement scope

The repeat upload contains 226,203 actual transaction rows. The incremental upload restores 10,000 real uniquely identified lines to a 216,203-row seed. Each fresh worker copies its seed before timing. Post-run assertions compare canonical transaction fingerprints and monetary/unit totals, and check SQLite integrity and foreign keys. They are excluded from the pipeline timings.

Memory is the Windows process peak working set, including worker setup but measured before post-run verification. The acceptance threshold is interpreted conservatively as 2,000,000,000 bytes (approximately 1.863 GiB), not 2 GiB. Hardware evidence is in `validation_outputs/integration_qa/environment.json`. These results establish local backend timing, not browser latency, simultaneous-user capacity or another computer's performance.

Three-trial measurements:

| Backend workflow | Median seconds | Time target | Largest peak working set |
| --- | ---: | ---: | ---: |
| Full-history repeat | 46.884 | 120 s | 1.655 GiB / 1.777 GB |
| 10,000-row increment | 54.245 | 180 s | 1.490 GiB / 1.600 GB |
| Full-history forecasting | 33.658 | 60 s | 0.582 GiB / 0.625 GB |

The repeat upload reports one within-file content duplicate and 226,202 already-known rows; it adds zero rows and preserves the historical 226,203 rows. Reconciliation does not silently remove historical duplicates. Each incremental trial adds exactly 10,000 rows and reproduces the full governed history.

`validation_outputs/integration_qa/final_performance.json` contains the authoritative nine-trial summary. Upload trials were repeated after the final dtype correction; forecast timings use the unchanged direct governed-data pipeline. The snapshot comparison checks every value and rowid in both directions across all seven tables, preserving duplicates and order. The final chunked restore also matches the original full SQL read exactly, including pandas dtypes. The governed prepared CSV SHA-256 remains `66b3aa57d6bb4352e04399370ba602fd368e378994dbf6fe38d343480502917e`.

## Methodology and data limitations

The actual forecast audit uses 226,203 source rows, 59 SKUs, 177 SKU/method scores and 17,136 validation predictions. Latest holdout actuals are all zero. RÂ² is therefore undefined for every method, including Linear Regression; raw MAPE is also undefined. Adjusted MAPE retains zero observations using its documented denominator floor. Small nonzero errors are displayed distinctly from exact zeros. These model-selection validation scores do not establish independent active-sales accuracy.

Approved MCA formulas are implemented. The available data does not provide the reconciled cost/net-sales ledger, daily stock history or explicit MCA measurement period needed for actual rankings. MCA use of the seven-day lead-time fallback remains an unresolved alternative; replenishment's labeled fallback already works independently. Missing criteria produce unavailable rankings rather than fabricated scores.

Final team visual acceptance and checks of the exact merged version on the intended integration computer remain external steps. This local candidate has not been pushed, merged or deployed.
