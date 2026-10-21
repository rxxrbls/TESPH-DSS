> Current policy update (October 21): equal-third baseline weights and reporting the historical baseline with its limitations are approved. Expanded-period checks and final validation remain required. Earlier pending-weight statements below describe the previous checkpoint. This is still a backup branch, not an issued handoff.

# Integration candidate setup and verification

> This branch is a work-in-progress backup. The instructions below are retained for local testing and future integration; no Member 3 handoff has been issued. See [current verification status](verification_status.md).

## Source and data

Optional local packaging: `python qa/package_candidate.py --readiness` creates `.artifacts/integration_candidate/tesph_sku_corrected_readiness_candidate.zip` after the documented private QA prerequisites exist. `CANDIDATE_MANIFEST.json` records source hashes, base commit, branch and separate corrected-data hashes. A ZIP is not needed to push this backup branch.

Start from a separate checkout of the team's repository. Compare and integrate candidate files rather than overwriting unrelated frontend work. Preserve the existing governed `final_outputs` handoff and authorized `raw_data` files. Datasets, live databases and real credentials are not bundled; the manifest records the required governed CSV hashes. `final_etl_handoff.py` regenerates governed outputs and must not be run as an application startup step.

The app is intended for local single-operator use. These checks do not establish concurrent-session consistency or public production-hosting readiness.

## Windows setup

Use the Python version recorded in the QA evidence when reproducing exact results. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

The archive's `tested-environment.txt` records installed versions for diagnosing differences. The project requirements retain supported dependency ranges. For an exact environment reproduction, install with `python -m pip install -r tested-environment.txt` in the new virtual environment.

Configure the local account using `.streamlit/secrets.toml.example` as the template for private `.streamlit/secrets.toml`, or set process-local `TESPH_AUTH_USERNAME` and `TESPH_AUTH_PASSWORD`. Do not commit the real secret file. Run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The normal app writes active state under `runtime_data/`, separate from immutable `final_outputs`.

## Regression and actual-data checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe validate_forecast_accuracy.py
.\.venv\Scripts\python.exe validate_approved_mca.py
```

`validate_approved_mca.py` verifies the legacy five-criterion compatibility path; its financial/lead-time requirements do not apply to the three-criterion workflow. For the current workflow, use `python qa/validate_three_criterion.py` and the corrected candidate reproduction instructions in [the draft integration notes](corrected_candidate_integration_handoff.md). Actual-data QA requires the authorized private datasets and seed artifacts. Dates are explicit historical assessment dates, not today's operational coverage. Final weights and baseline acceptance remain provisional.

## Isolated performance checks

```powershell
.\.venv\Scripts\python.exe -u qa/benchmark.py --prepare
.\.venv\Scripts\python.exe -u qa/benchmark.py --runs 3 --label final
```

Preparation creates isolated databases under ignored `.artifacts/qa` and needs several GB of free disk space. The repeat CSV contains all 226,203 actual source rows. The incremental fixture restores 10,000 real uniquely identified lines removed from a 216,203-row baseline. No fabricated orders are used. Every trial copies its original seed. Preparation and post-run verification are outside the timed pipeline. Fingerprints, row counts, quantities, monetary totals and SQLite integrity are verified after uploads.

Run benchmarks alone, with other expensive jobs stopped. Workers use fresh Python processes and Windows peak-working-set counters. Process peaks include setup. Timings cover backend upload/reconciliation/publication; browser-visible post-upload analytics/forecasts are separate. Compare medians with 120s repeat, 180s incremental and 60s forecast targets, and memory with the 2 GB target on a machine with at least 8 GB RAM. Record units and hardware.

## Local browser acceptance

After benchmark preparation, with Edge installed:

```powershell
.\.venv\Scripts\python.exe -u qa/check_uploaded_mca.py
.\.venv\Scripts\python.exe -u qa/browser_check.py
```

The runner launches headless Edge and its own local Streamlit server. A temporary entry point changes runtime paths and test credential configuration; login validation, routing, pages and pipelines use production code. Generated credentials exist only in that child process. The user's live runtime database and password are untouched. Screenshots/results are saved under `validation_outputs/integration_qa/browser/`. The temporary entry point is removed and server stopped on exit.

Review the captures manually, then repeat login, upload, duplicate upload, invalid input, forecast, stock validation, risk, prioritization and replenishment on the actual combined frontend build. Automated tests additionally cover stale/future stock, state invalidation, changed/ambiguous transactions, locking, persistence failure and missing inputs.

## Packaging and acceptance

```powershell
.\.venv\Scripts\python.exe qa/package_candidate.py
```

Every included file is verified against its checksum. The archive includes current forecast/MCA audit tables and integration QA summaries/screenshots; raw transaction data, runtime databases and logs are excluded. Hand the archive/manifest to the team through the established process, with authorized data supplied separately. This command does not push, merge or deploy.

After integration, record the final commit, dataset checksums, configuration, regression results, measured performance, browser evidence, unresolved MCA inputs and accepted limitations. Final visual acceptance and deployment-machine checks belong to that exact version.
