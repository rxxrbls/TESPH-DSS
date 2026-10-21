> Final TA decision (October 21, 2026): historical validation accepted; equal thirds approved; no further historical return data required. Earlier results below remain dated evidence. Synthetic staging validation is recorded in `synthetic_mca_validation.md`. Combined-build acceptance is still required.

# Three-criterion MCA: technical implementation and TA review

Date: October 20, 2026. Status: conditionally authorized implementation and testing; final weights are not locked. This report supersedes earlier statements that the three-criterion workflow is unimplemented.

> Current corrected-candidate checks: see [verification status](verification_status.md) and [integration handoff](corrected_candidate_integration_handoff.md). The 59-SKU results below describe the earlier uncorrected baseline.

## Actual-data findings

The assessment uses 226,203 sales transactions and 3,705 return/refund item lines (2,839 requests). The uploaded stock catalog produces 60 forecast SKUs. Of these, 59 meet the provisional three-criterion requirements; one has no positive eligible-order denominator and remains unavailable.

Both provisional weight scenarios were calculated on the same 59 eligible SKUs:

| Scenario | Sales Velocity | Forecasted Demand | Recorded Return/Refund Quantity Rate |
| --- | --- | --- | --- |
| Equal thirds | 1/3 | 1/3 | 1/3 |
| TA alternative | 25% | 25% | 50% |

Pearson and Spearman correlations are undefined because forecast demand is exactly zero for all eligible SKUs. The recorded return/refund rate is also zero for all 59 eligible SKUs. The eligible SKU subset matches only one request line, which is cancelled and therefore not counted. The remaining return/refund records concern other product identities; they must not be reassigned to current SKUs merely to produce nonzero rates.

Consequently, changing weights produces zero rank changes and zero priority-group changes. Both constant criteria normalize to 0.5. Only Sales Velocity differentiates scores; ties use the existing deterministic SKU ordering and 25/50/25 ceiling groups. This is not evidence of low correlation, of effective quality differentiation, or of three independent signals.

Of all request lines, 2,134 are counted under the recorded refunded-status rule, 1,523 are cancelled/rejected and not counted, and 48 remain unresolved disputes. These totals describe the complete request dataset, not refunded units for the current 59-SKU ranking population. A request with multiple product lines generates multiple line-level review events.

Evidence: `validation_outputs/three_criterion_mca/summary.json`, `mca_audit.csv`, `equal_thirds.csv`, `volume_quality.csv`, and `sensitivity.csv`. Detailed request records remain in private `.artifacts/qa/` files.

## Implemented behavior

1. A separate three-criterion policy uses Sales Velocity and Forecasted Demand as benefit criteria, and Recorded Return/Refund Quantity Rate as a cost criterion. Product cost, profit margin and supplier lead time are not three-criterion MCA requirements.
2. The rate is 100 × eligible recorded refunded units / eligible ordered units. Matching uses Order ID, product, variation and product key. The denominator uses the existing Completed/Returned demand-order definition within the explicit order-date period.
3. Request Refunded quantities may count for Refund Only and Return Refund solutions. They are recorded refund quantities, not proven physically returned units. Cancelled/rejected requests do not count. Dispute labels and completion dates alone do not resolve ambiguous outcomes.
4. Missing or invalid quantities, unsupported solutions, unmatched evidence, conflicting request statuses, excess quantities and multiple potentially effective requests for the same order/product remain unresolved. Cancelled/rejected attempts do not themselves become counted quantities. Distinct Return IDs remain separate.
5. Missing coverage, no positive denominator or unresolved relevant evidence makes the rate unavailable. All three criteria must be finite before normalization. Missing values are never imputed as 0.5; 0.5 applies only to valid constant criteria.
6. Both weight scenarios use full-precision scoring and the existing deterministic ranking/grouping functions. The displayed scenario is explicitly provisional equal thirds; sensitivity outputs compare it with 25/25/50.
7. Every accepted return/refund batch and connected stock refresh re-evaluates stored evidence. Accepted sales batches, including duplicate uploads, also trigger review. Sales refresh invalidates stock-dependent rankings until a connected stock refresh recomputes them.
8. Partial return uploads upsert explicit request/product evidence and retain absent records. Disappearance from an upload cannot silently clear a dispute.
9. SQLite persists original merged evidence snapshots by hash, latest review state, derived tables and append-only review events. Each event includes batch/run ID, UTC review time, source status transition, system decision transition, reason, product/SKU, source hash, coverage, policy version and snapshot age. The UTC local review time does not reinterpret Shopee's unspecified timezone.
10. A failed return/stock calculation does not publish its candidate snapshot, audit events or outputs. Sales and review storage are separate transactions: if sales commits but review fails, sales remains accepted, the failure is reported, and MCA must remain unavailable pending a successful refresh. This is not claimed as a distributed atomic transaction.

## Application use and integration flow

Process sales, then connect a valid current-stock snapshot on Data Upload & ETL. Open **Return/refund data — three-criterion MCA**, choose the cleaned backend CSV or handoff ZIP, review the dates, and confirm selected-window coverage. Submit **Validate and refresh three-criterion MCA**.

The application validates the evidence, matches it to sales, reviews requests, calculates eligibility, compares provisional weights, and refreshes MCA and recommendations. Product Prioritization displays the three criteria, provisional status and downloadable readiness, rankings and weight comparison.

Before the first return upload, the existing five-criterion path remains available for backward compatibility and is labeled legacy. Importing three-criterion evidence activates the new path for subsequent connected refreshes. Existing five-criterion callers/tests remain supported; do not mistake the legacy configuration constants for the new policy.

The three-criterion assessment rejects sales extending beyond its selected historical endpoint and forecasts starting on a different day from the following day. Update assessment coverage deliberately when new sales are supplied; do not combine future sales/forecasts silently with a fixed historical assessment.

## Files and functions to preserve

| File | Responsibility |
| --- | --- |
| `three_criterion_mca.py` | Explicit coverage, snapshot validation, exact matching, request decisions, rates, weight scenarios, correlation and sensitivity |
| `return_refund_store.py` | Persistent snapshots and append-only audit; atomic review/output publication |
| `mca_refresh.py` | Shared connected-refresh adapter and accepted-sales review trigger |
| `prescriptive_pipeline.py` | Three-criterion option joins approved forecast/analytics/stock outputs and recomputes recommendations |
| `prescriptive_calculations.py` | Reused Min-Max normalization, precision, ranking, ties and priority bands; explicit criteria argument |
| `etl_streamlit.py`, `runtime_data_store.py` | Hooks on accepted sales batches, including repeats |
| `pages/data_upload.py` | Explicit evidence upload/coverage controls and stock refresh integration |
| `pages/product_prioritization.py`, `utils/state.py` | Provisional labels, formatted copies, raw CSVs and invalidation |
| `qa/validate_three_criterion.py` | Isolated actual-data assessment and diagnostics |
| `qa/browser_check.py --three` | Browser acceptance and backend/download comparison |
| `tests/test_three_criterion_mca.py` | Hand calculations, invalid evidence, review lifecycle, weighting and frontend regression |

The review database sits beside the active transaction database as `<transaction database stem>_return_review.db`. Preserve and back it up with the transaction database. It contains business records and must not be committed or packaged publicly. SQLite is from the Python standard library; this revision adds no runtime package dependency.

Existing ETL reconciliation, forecasting selection/validation, current-stock identity rules, stock-risk formulas and replenishment fallbacks remain governed by their existing contracts. The five-criterion historical package and test evidence are historical, not proof of this revision.

## Coverage and limitations

Order period: May 22, 2020–April 24, 2026. Selected request dates: May 1, 2020–April 24, 2026. Export requests: October 15–16, 2026, with timezone unspecified. Exact export times are not needed to proceed.

These are selected-window recorded outcomes, not lifetime returns. Later requests for April orders are absent. The monthly manifest and cleaned records are available; original monthly workbook bytes and duplicate-export version lineage cannot be independently verified from this handoff. See `return_refund_coverage_record.md`.

The September 9 stock snapshot and April 24 sales endpoint do not form a current operational assessment. These outputs must be labeled historical/scenario-based. No automatic local refresh obtains newer Shopee outcomes.

## Verification and remaining steps

Full project regression: **428 passed**, one warning, 94.85 seconds. Evidence: `validation_outputs/three_criterion_mca/pytest_full.txt`. The final targeted run also passed 25 tests covering request review, connected scoring/display and shared-state invalidation.

The actual-data assessment completed in 44.02 seconds on this workstation, including loading, forecasting, analytics and review/scoring. This is one observed run, not a benchmark guarantee for the integrated or deployed system.

Final browser acceptance: **19 checks passed**, no browser errors. Checks used real transaction/stock/return files in an isolated runtime. All three MCA CSV downloads matched the independent backend results. Repeat return uploads appended new review events without duplicating quantities, and a repeat sales upload automatically re-evaluated the stored requests. Login, forecast metrics, connected pages and the mobile viewport also passed. Evidence: `validation_outputs/three_criterion_mca/browser/summary.json` and adjacent screenshots. The earlier browser failure was a test synchronization issue: the assertion ran before the second review committed; the final check waits for the committed events.

Browser results and package receipt are recorded in `validation_outputs/three_criterion_mca/`. The new source candidate is `.artifacts/integration_candidate/tesph_three_criterion_provisional.zip`; the earlier five-criterion candidate is preserved separately. Run `python qa/package_candidate.py --three` to rebuild the provisional candidate and verify every packaged source hash.

TA decisions: select the final weight policy in view of the undefined correlation and identical ranks; confirm whether to report this baseline explicitly as a limited historical scenario, or require a separately justified historical population/assessment with variable criterion values. No assumed costs, lead times, fabricated returns or date shifting were introduced to make the baseline look more informative.

Member 3 still needs to merge the reviewed candidate with the actual frontend and rerun acceptance on that exact combined version and intended deployment computer. Local browser acceptance is not production sign-off. No remote commit, merge, deployment or publication to Google Docs is included in this report.
