# Technical reference for the integration member

Prepared locally for the final approval checkpoint on `sab-week3`; read `integration_candidate_setup.md` for current approval status. No handoff or merge has been issued.

## System flow

1. Authentication and upload validation accept sales files; ETL preserves original identifiers and validates schema/types.
2. Runtime persistence reconciles repeats and corrections, publishes dataset identity and invalidates stale derived outputs. Governed CSVs and mutable runtime state have different roles.
3. Analytics aggregates eligible sales. Forecasting builds SKU histories, performs chronological validation and model selection, then publishes forecasts and accuracy metrics.
4. Stock upload resolves exact product identities, excludes ambiguous/duplicate stock pools and connects inventory to forecasts. Stock-risk/replenishment retain their documented fallback assumptions; these are not MCA lead-time criteria.
5. Cleaned return/refund input plus explicit coverage is matched to eligible orders/products. Review rules distinguish counted, excluded and unresolved evidence. Persistent review events are updated during accepted batch refreshes.
6. The three-criterion pipeline combines Sales Velocity, Forecasted Demand and Recorded Return/Refund Quantity Rate. Eligible complete rows determine normalization bounds. Equal-third scores are ranked with existing tie/group rules; sensitivity is reported separately.
7. Pages and downloads display backend results. Missing results remain N/A. Dataset changes invalidate dependent state before recomputation.

## Calculations and safeguards to preserve

- Preserve existing demand-status definitions, chronological train/validation split, forecast alignment and approved model-selection rules. MAE/RMSE/MAPE/R² must use actual aligned validation pairs; undefined metrics stay unavailable.
- Sales Velocity uses the existing eligible-sales aggregation/window. Do not replace it with lifetime totals during merging.
- Recorded refund quantity rate = 100 × eligible counted recorded refunded units / eligible ordered units, using matching orders/SKUs and the explicit assessment period. Recorded units are not proven physically returned units.
- Request Refunded quantities count only when other validation rules permit. Cancelled/rejected requests do not count. Dispute labels or completion dates alone do not establish final outcomes.
- Distinct Return IDs remain distinct requests. Conflicting or potentially overlapping effective requests, uncertain quantities, excess quantities and unresolved relevant disputes remain flagged. Do not sum blindly or resolve an absent record by assuming it vanished.
- Missing coverage, nonpositive denominator or unresolved relevant evidence produces unavailable rate/ranking. A legitimate zero is different from missing data.
- Three finite criteria are required. Min-Max normalization uses complete rows; constant valid criteria receive 0.5. Missing values never receive 0.5. Preserve benefit/cost directions, full precision, deterministic SKU ties and existing 25/50/25 ceiling priority groups.
- Equal weights are the approved baseline. Preserve the separate 25/25/50 sensitivity calculation; it is not the active policy.
- Every accepted sales batch (including repeats), return/refund batch and connected stock refresh must retain dispute re-evaluation behavior. Source evidence and decision history must remain traceable. Review failure cannot publish stale MCA as valid.
- Sales and review persistence are separate transactions: if sales commits and review fails, report the review failure and withhold MCA until successful refresh. Do not claim distributed atomicity.

## Merge-sensitive files

| Modules | Preserve |
| --- | --- |
| `etl.py`, `etl_streamlit.py`, `runtime_data_store.py` | Identifier handling, duplicate/correction safeguards, dataset identity, accepted-sales refresh hooks |
| `active_inventory.py` and crosswalk logic | Exact unique mapping and duplicate-SKU/stock-pool exclusions |
| `sku_forecasting.py` and forecasting calculations | Time alignment, validation metrics, model selection and forecast output contract |
| `three_criterion_mca.py`, `prescriptive_calculations.py` | Eligibility, matching, rate definitions, normalization, weights and ranking |
| `return_refund_store.py`, `mca_refresh.py` | Evidence upsert, persistent audit, re-evaluation and rollback behavior |
| `prescriptive_pipeline.py` | Three-criterion activation and connected downstream calculations |
| `pages/data_upload.py`, `pages/product_prioritization.py`, `utils/state.py` | Coverage controls, labels, N/A, CSV precision and stale-state invalidation |
| `tests/`, `requirements*.txt` | Regression contracts and dependencies |

Retain legacy five-criterion compatibility where callers depend on it. The three-criterion upload activates the new workflow; do not confuse legacy configuration with the active approved baseline.

## Known limitations and remaining decisions

Most original transactions lack SKUs; exact recovery improves coverage but does not repair absent identities. Most return records cannot be mapped to the accepted catalog. Complete source history is not complete SKU-level analytical coverage.

December–February runs demonstrate two varying criteria and ranking changes versus Sales Velocity alone. All eligible refund rates remain zero; March forecast magnitudes are negligible. These results do not prove all three criteria improve business outcomes. Request-date coverage and retrospective October status snapshots limit historical interpretation.

TA historical model validation is accepted. Actual combined-build acceptance remains open. Local source packaging, component checks and historical tests do not substitute for testing Member 3's merged frontend on the demo machine.
