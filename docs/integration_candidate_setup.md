# TESPH-DSS integration preparation — October 21, 2026

**LOCAL DRAFT — not yet issued to Member 3. TA historical validation is accepted.**

Source: final approval update on `sab-week3`; see the packaged manifest for the exact source commit. No merge or deployment has been performed. This note supersedes stale approval/test-count wording in the frozen historical documents without altering that source checkpoint.

## Current decisions and evidence

- Equal weights (1/3 each) are TA-approved. Historical baseline reporting with its limitations is approved. The 25/25/50 option is a sensitivity comparison only.
- Latest saved regression: **432 passed**, one existing pandas date-parsing warning. See `validation_outputs/integration_readiness/pytest_final_approval.txt`. Packaging verifies hashes; it does not constitute another regression or combined-frontend test.
- Corrected full transaction CSV: **226,203 rows, 76 columns**. Its matching database and six Star Schema CSVs were independently compared. Use the entire corrected set together.
- With the documented raw stock source, prior corrected-candidate checks produced 67 accepted catalog products, 62 forecast SKUs and 61 MCA scores. One forecast SKU remained unavailable. These counts are conditional on the same inputs/configuration, not permanent expectations for new data.
- April baseline forecasts and counted refund rates remain zero among ranked SKUs. Earlier December–February assessments have non-negligible forecast variation; refund rates remain zero. See `docs/historical_variance_checks.md` and `validation_outputs/historical_variance/`.
- The TA accepted these results for final model sign-off; no further historical return-data collection is required. No evidence yet establishes improved business prioritization or sensitivity with varying refund rates. March's tiny positive forecast is not meaningful demand variation.

## Package contents

- `source.zip`: selected application source, tests, technical documents and QA evidence from the clean frozen checkpoint. Includes dependency snapshot. Private transaction data and credentials are excluded.
- `PRIVATE_DATA.zip`: corrected CSV/database set, supplementary governed workbooks, stock inputs and cleaned return/refund backend CSV. **Contains private business/customer records. Keep local or use the team's authorized private transfer; do not upload it to GitHub.**
- `MANIFEST.json`: source/data/archive SHA-256 values, commit and environment version.
- `tested-environment.txt`: installed dependency versions for reproduction.
- `corrected_candidate_integration_handoff.md`: flow, rules and merge-sensitive modules.
- `member3_acceptance_checklist.md`: checks for Member 3 after integration, with explicit uncompleted items.

## Setup in a separate test folder

1. Preserve the existing frontend checkout and any live database. Extract `source.zip` into an empty test folder; do not overlay an operational checkout. Member 3 later merges reviewed code changes into their branch, preserving unrelated frontend work.
2. Verify both archive hashes against `MANIFEST.json` using PowerShell `Get-FileHash -Algorithm SHA256`. Extract `PRIVATE_DATA.zip` into that same empty test folder. It places the corrected database at `runtime_data/active_transactions.db` and the coherent CSVs under `final_outputs/`.
3. Create a virtual environment using the Python version in the manifest. Run `python -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -r tested-environment.txt`. The repository's `requirements-dev.txt` is the supported-range alternative; record any differences.
4. Configure private login credentials using `.streamlit/secrets.toml.example`. Never commit real credentials. Start `.\.venv\Scripts\python.exe -m streamlit run app.py`.
5. The supplied database contains sales state, not an activated return-review history. Use Data Upload & ETL to connect `raw_data/current_stock/shopee_current_stock_raw_2026-09-09.xlsx`, then upload `private_inputs/prepared_return_refund_backend.csv` in the three-criterion return/refund section. Follow its validation prompts and refresh connected outputs.
6. Explicit historical dates: orders **May 22, 2020–April 24, 2026**; selected return-request creation coverage **May 1, 2020–April 24, 2026**. Exports were requested October 15–16, 2026, timezone unspecified. Confirm only documented selected-window coverage; this is not complete lifetime refund coverage. Export Request Time is not proven to be a universal status-update cutoff.
7. Record the configured assessment/as-of dates. September stock with April-ending sales is a historical/scenario combination, not proof of current operational validity. Do not bypass stale-stock safeguards to reproduce old counts.
8. Run the acceptance checklist. Record results on the exact merged commit and intended demo computer before claiming final integration readiness.

Do not run `final_etl_handoff.py` or the legacy standalone ETL as an app-startup step. Do not substitute the earlier subset `source_exact_candidate.csv` or the 216,203-row incremental benchmark seed for the corrected full dataset.

Some historical QA reproduction scripts require original raw workbooks, benchmark seeds and investigation artifacts not included here. Their saved results are included, but they are not one-command acceptance tests for a fresh installation. Supply those prerequisites separately if full audit reconstruction is needed; do not fabricate substitutes.
