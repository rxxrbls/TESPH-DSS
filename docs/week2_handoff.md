# Week 2 Analytics Handoff

## Scope and status

The Week 2 implementation is on `sab-week2`. `analytics_app.py` is the runnable
descriptive/predictive dashboard. Integration into another branch's authenticated
application is separate. Source exports are not manually modified.

All nine previously remaining tickets are implemented. "Done" means code,
documented decisions, and local verification, not independent TA/client sign-off,
production deployment, or repair of unavailable source identifiers.

### The nine remaining tickets

| Ticket | Status | Completion evidence |
| --- | --- | --- |
| KAN-269 | Done | Central configuration and JSON enforce MAPE/RMSE priority and daily SKU forecasts. |
| KAN-270 | Done | Descriptive rules compared with repository methodology sections 2-4 and handoff; sources and limitations recorded below. |
| KAN-271 | Done | Consistent definitions retained; product returned-line denominator aligned with returns view; malformed inputs rejected. |
| KAN-113 | Done | MAPE first, RMSE second, alphabetical exact tie; explicit RMSE fallback when raw MAPE is undefined for all methods. |
| KAN-114 | Done | Hand-calculated tests, regression suite, independent real-data totals and forecast validation. |
| KAN-115 | Done | Daily 3/7/14/30 windows scored on common inner holdouts by MAPE/RMSE, without outer-holdout leakage. |
| KAN-116 | Done | Zero observations retained; one-unit denominator-floor adjusted MAPE, raw MAPE, zero counts and explicit labels. |
| KAN-117 | Done | Active flags, current-catalog evidence, approved override mapping, identity checks and exclusions. Missing identities remain excluded. |
| KAN-118 | Done | End-to-end checks of configuration, SKU grain, selection, temporal splits, exclusions and bottom-up totals. |

### Other Week 2 tasks checked

| Tickets | Implementation |
| --- | --- |
| KAN-105, KAN-106, KAN-278 | Sales summary, product performance, monthly trends, date/category filters, CSV exports. |
| KAN-279, KAN-280 | Returns, order-status totals, cancellation reasons/quantities, distinct-order denominators. |
| KAN-281, KAN-237 | Movement, category low-sales percentiles, review flags, sales velocity. |
| KAN-238, KAN-272 | Manual descriptive arithmetic and prepared/star-schema reconciliation. |
| KAN-242 | String identifiers, continuous variation histories, zeros only within covered history. |
| KAN-243, KAN-244, KAN-245 | MA, ES and Linear Regression independently per eligible SKU. |
| KAN-246, KAN-247, KAN-248, KAN-249 | MAE, RMSE, MAPE, R2, observation/zero counts and undefined states. |
| KAN-107, KAN-108, KAN-109 | Actual/forecast chart, selected method, metrics, validation tables and ZIP. |
| KAN-110 | Product/category totals sum SKU forecasts, never substitute category models. |
| KAN-111 | ES alpha minimizes squared error; final parameters retuned on available history. |
| KAN-112 | Expanding rolling origins, common horizons/dates, tuning inside each training split. |

## Authority and decisions

The supplied TA conversation (September 11/14) establishes SKU forecasting,
bottom-up totals, dynamic ES alpha and MA windows, MAPE/RMSE model selection,
retention of zeros, and active/client-approved scope. It does not specify the
zero-demand formula or every operating parameter. The leader's clarification
authorizes the team to make those technical decisions.

Existing local `PROPOSED_ANALYTICS_METHODOLOGY.md` sections 2-4 and
`ANALYTICS_HANDOFF.md` describe the descriptive definitions below. These are
repository records, not newly obtained signed approval. The TA transcript does
not reproduce the descriptive formulas. We retain consistent descriptive rules
as the team's baseline, with test evidence, and supersede old forecasting rules
where newer TA notes differ.

| Setting | Implemented decision |
| --- | --- |
| Frequency/horizon | Daily gross demand; next 7 days after sales coverage. |
| Outer validation | Latest up to 14 feasible expanding origins; 7-step horizon; at least 37 training days. |
| Inner tuning | Latest up to 7 feasible origins; common candidate dates; shorter inner horizon only when history cannot support the configured horizon. |
| MA windows | 3/7/14/30 days, feasible windows only; adjusted MAPE, RMSE, smaller window for exact ties. |
| ES alpha | 0.1 through 0.9; minimum RMSE equals minimum SSE with equal counts; MAE then smaller alpha breaks ties. |
| Final model | Lowest adjusted MAPE, then RMSE, then alphabetical method name; no rounding before selection. |
| Zero-demand score | `100 * mean(abs(actual - forecast) / max(abs(actual), 1))`; one unit is a team choice; every zero observation contributes. |
| Raw MAPE | Undefined when any actual is zero; separately reported, never drops zero rows. |
| Optional raw policy | `return_nan`: all undefined -> RMSE then name; mixed undefined/defined coverage is rejected. |
| Catalog recency | Default 90 days; configurable `max_age_days` on `build_active_mapping`. |

Adjusted MAPE is not ordinary MAPE. Its floor limits tiny-denominator effects and
penalizes overforecasts on zero days. Machine-readable `MAPE` is the configured
score; `MAPE Status`, `Raw MAPE` and `Selection Basis` accompany the outputs.
The dashboard labels the default score "Adjusted MAPE".

MA recursively appends predictions for multi-step horizons. ES repeats its final
smoothed level. Linear Regression uses time-index OLS, clipping negative demand
to zero. MAE is mean absolute error; RMSE is root mean squared error; R2 is
`1 - SSE/SST`, undefined for constant actuals or fewer than two observations.
Undefined values display N/A, not zero.

Each origin/step has equal metric weight; overlapping horizons can repeat a date
at different origins. The chart offers an origin selector. Scores are
model-selection validation scores, not an independent unbiased evaluation of the
chosen winner. Final tuning uses all covered history without rewriting backtests.

## Descriptive definitions

| Metric | Exact rule |
| --- | --- |
| Gross revenue | Sum line Total Buyer Payment on ETL completed rows; excludes cancelled/unpaid. Not profit or seller payout. |
| Gross demand | Sum Quantity when completed OR returned; overlapping flags count once. |
| Net inventory demand | Sum per-line max(gross demand minus demand-returned quantity, 0). |
| Returned quantity | Actual Returned quantity on demand lines, not all ordered units on return-flagged lines. |
| Average order value | Gross revenue / distinct completed Order IDs. Repeated order IDs remain valid lines. |
| Return quantity rate | Demand-returned units / gross demand. |
| Return order rate | Distinct return-flagged Order IDs / distinct demand Order IDs. |
| Returned-quantity line rate | Demand lines with positive returns / demand-line count, consistent in product and returns views. |
| Cancellation order rate | Distinct cancelled orders / distinct all orders. Cancellation quantity uses cancelled lines. |
| Average unit revenue | Gross revenue / completed quantity. |
| Net revenue after returns | Completed-line payment times net/gross demand ratio; proportional estimate, not refund settlement. |
| Monthly trends | Monthly category sums, covered no-sales periods represented as zero. |
| Sales velocity | Gross demand / complete periods in the analysis window. |
| Movement | Latest 3 complete months: 3 positive months fast, 2 regular, 1 slow, 0 no movement. |
| Low sales | Positive recent demand <= category's 25th percentile of positive demand; review flag, not deletion. |
| YoY | (Current comparable revenue - prior-calendar-year comparable revenue) / prior comparable revenue. |

Zero denominators and missing prior years yield undefined rates. Categories with
no positive demand have no positive-demand percentile. Order counts across
products/categories are not additive when orders span groups. Movement/velocity
use the global selected coverage end; complete-month calculations exclude a
partial final month. YoY needs complete comparable source coverage: a partial
first year does not prove earlier zero sales.

## Eligibility and source limitations

Default catalog:
`raw_data/current_stock/current_stock_inventory_2026-09-09.csv`.
The team rule treats presence in a fresh current catalog as activity, not client
approval. Only unique exact historical product-key matches with real non-reused
SKUs, valid nonnegative stock and recent dates qualify. Source SKU conflicts are
excluded. Zero stock is not inactivity. Explicit catalog active/category_active
false flags override presence. A category is active if it contains accepted SKUs.

Catalog-derived mappings keep `client_approved=False`, recording
`catalog_active`, `Eligibility Basis` and `Stock As-Of Date`. A reviewed mapping
can explicitly approve historical-to-current identities. Required CSV fields:
`product_key, SKU, Product, Category, active, category_active, client_approved`.
Flags accept true/false or 1/0. One row per historical key; multiple keys can map
to one SKU only with consistent metadata/activity. Template flags start false.

September 26 catalog check, 1,980 rows:

| Result | Rows |
| --- | ---: |
| Missing source SKU | 1,712 |
| No exact historical match | 112 |
| Reused SKU / unresolved stock pool | 90 |
| Historical/current SKU conflict | 2 |
| Accepted exact matches | 64 |

59 of 64 matches have sufficient history; 5 do not. All 2,116 historical keys
remain in eligibility, including 2,052 lacking eligible mappings. Exclusions do
not prove inactivity and do not justify invented identities. Daily calendars
expand only mapped candidates; all historical keys remain audited.

Sales end **2026-04-24**; forecasts cover **April 25-May 1**, not September.
The dashboard warns these are historical-only. Refresh ETL sales before current
inventory decisions. Inventory dates never extend sales coverage or create
months of zero sales. Calendar zeros start after first observation and require
covered exports; missing exports are not evidence of no demand.

Product/category totals cover only forecast eligible SKUs, not the whole
business. SKU error metrics are not averaged into aggregate accuracy. Legacy
seasonal/category APIs remain compatible; Week 2 uses three base SKU models.

## Run and verify

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python verify_analytics.py
python verify_week2.py
python forecasting_pipeline.py --config config/forecast.example.json --output-dir .artifacts/week2-final
python -m streamlit run analytics_app.py
python tests/browser_week2.py
```

Browser checks expect port 8501, Edge and Playwright. They cover real desktop/
mobile sales and forecasts, chart pixels, logo loading, exceptions and overflow.
Streamlit interaction tests use synthetic mappings, not invented client approval.

Normal Python passes 105 calculation tests (UI skipped without Streamlit).
All 109 tests pass in `.runtime`, including four Streamlit interaction tests;
set `$env:PYTHONPATH='.runtime'` to use it.

Real descriptive reconciliation: 226,203 lines, 133,586 orders, PHP 25,366,956
gross revenue, 637,356 gross demand and 637,133 net inventory demand.
`verify_week2.py` independently checks errors, holdout dates, selection,
eligibility, horizon and bottom-up sums. Exports/screenshots stay in ignored
`.artifacts/` and `.runtime/`.

Remaining operational work: fresh sales data, data-owner resolution of excluded
identities, and integration/deployment in the main app. These are not additional
TA questions or claims of completed production rollout.
