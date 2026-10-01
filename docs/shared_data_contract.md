# TESPH DSS Shared Data Contract

**Version:** 0.1 (foundation)  
**Purpose:** Define the interface boundaries between ETL, analytics, forecasting, stock-out risk, prescriptive analytics, and the Streamlit UI. This is a handoff contract, not an implementation of any calculation.

## Principles

- The original Shopee export is the source of truth for raw source fields. ETL must retain the raw file and document its source-column mapping; this contract does not assume a fixed set of Shopee export headers.
- Fields marked **derived** are created only by an approved downstream module and must never overwrite raw source values.
- CSV and XLSX are accepted by the UI. Member 2 owns reading, validation, cleaning, and canonical-output creation.
- `sku` is the primary product identifier when it is present and usable. A module must not invent SKU values. If unavailable, it must retain the explicit fallback identifier and document that limitation.
- All datasets passed between modules should be tabular (for example, Pandas DataFrames) with the canonical field names below, plus lineage metadata describing source file, extraction time, and contract version.

## Application state interface

The Streamlit session uses `utils.state.DataStatus`:

| State | Meaning | Owner of transition |
|---|---|---|
| `NO DATA` | No successfully processed canonical dataset is available. | Application initialization / ETL failure or reset flow (future) |
| `PROCESSING` | A selected source file is being handled by ETL. | ETL orchestration |
| `DATA READY` | ETL has produced a validated canonical dataset suitable for connected modules. | ETL completion only |

The current upload page runs the ETL workflow for a selected file. It transitions
to `DATA READY` only after validated in-memory results and SQLite persistence
both succeed.

## Upload persistence and historical handoff boundary

`final_outputs/prepared_transactions.csv` and the accompanying historical
Star-Schema CSV/XLSX files are immutable governed Member 1 handoff artifacts.
Normal Streamlit uploads never write them.

The first successful upload bootstraps `runtime_data/active_transactions.db`
from the governed prepared-transaction baseline. Every later validated upload
is reconciled against that active history before a candidate SQLite snapshot is
atomically published. The runtime database contains the consolidated
`prepared_transactions`, six materialized Star-Schema tables, metadata, and a
compact ingestion-batch audit. It is the local single-operator runtime
authority.

The Streamlit `ETLResult`, session `prepared_transactions`, session
`star_schema`, descriptive analytics, and forecasting all refer to the same
published active snapshot. A failed upload or reconciliation leaves the
previous runtime snapshot and session data intact. Current-stock inventory is a
separate temporary snapshot and never changes transaction history.

## Canonical transaction interface: ETL → descriptive analytics

ETL should provide a transaction-level table named conceptually `canonical_transactions`. Every column below is conditional on its source availability and validation. Raw source names remain preserved through a documented mapping.

| Canonical field | Type | Origin | Convention |
|---|---|---|---|
| `transaction_id` | string | source if available | Identifier for an order line/transaction according to documented source granularity; never fabricated as an authoritative Shopee ID. |
| `order_id` | string | source if available | Raw order identifier, preserved as text to retain formatting. |
| `order_date` | datetime64 / date | source | Business/order date selected by ETL and documented; date-only analytics use `YYYY-MM-DD`. |
| `raw_product_name` | string | source | Exact product name from the Shopee export. Never overwrite, trim away keywords, or replace with a display label. |
| `standardized_product_name` | string | **derived** | Optional separate normalized display/grouping field. It must retain a traceable relationship to `raw_product_name`. |
| `sku` | string | source if available | Primary product identifier. Preserve leading zeros and source formatting; null remains null, never an invented code. |
| `category` | string | source or documented mapping | Category label as supplied or mapped by an approved, documented rule. Do not hard-code current client categories. |
| `quantity` | integer / decimal | source | Transaction quantity/demand unit with source meaning documented (sold, ordered, etc.). |
| `unit_price` | decimal | source if available | Monetary amount before/after discounts only when the source semantics are documented. |
| `order_status` | string | source if available | Raw/canonical status needed for later eligibility rules. |
| `current_stock` | integer / decimal | source or separate inventory input | Current on-hand stock measured at a documented as-of timestamp; not inferred from sales rows. |

ETL may add auditable quality/lineage fields (for example `source_file_name` and `source_row_number`) when needed, but they are not business metrics. Missing source fields must remain explicitly unavailable rather than being silently synthesized.

## Aggregated product/demand interface: descriptive analytics → predictive analytics

Forecast preparation should receive a category/product time series containing at least:

| Field | Type | Origin | Convention |
|---|---|---|---|
| `period_start` | datetime64 / date | **derived** | Start of the documented aggregation interval. |
| `period_end` | datetime64 / date | **derived** | End of the documented aggregation interval. |
| `category` | string | canonical transaction data | Same category convention as above. |
| `sku` | string | canonical transaction data | Use when forecasting/product analysis is SKU-granular. |
| `demand_quantity` | integer / decimal | **derived** | Aggregated eligible quantity. Its inclusion/exclusion rules must be documented by the analytics owner. |

Forecast-category selection must support **up to three** eligible categories: select three when at least three are eligible, otherwise select the number available; zero eligible categories produces an insufficient-data state. No category names are assumed by this contract.

## Forecast output interface: predictive analytics → risk/prescriptive/UI

| Field | Type | Origin | Convention |
|---|---|---|---|
| `forecast_period_start` | datetime64 / date | **derived** | Forecast interval start. |
| `forecast_period_end` | datetime64 / date | **derived** | Forecast interval end. |
| `category` | string | canonical data | Forecasted category, if category-level. |
| `sku` | string | canonical data | Product identifier if product-level forecast is supported. |
| `forecast_demand` | float / decimal | **derived** | Predicted demand quantity for the documented horizon. |
| `forecast_method` | string | **derived** | Method label supplied by predictive module. |
| `forecast_status` | string | **derived** | Explicit result status, including insufficient data where applicable. |

Accuracy metrics (MAE, RMSE, MAPE, R²) may be emitted later by the predictive module with their evaluation-period metadata; they are not calculated by this foundation.

## Stock-out risk output interface: risk module → prescriptive/UI

| Field | Type | Origin | Convention |
|---|---|---|---|
| `sku` | string | canonical data | Primary product identifier when available. |
| `current_stock` | integer / decimal | canonical inventory input | Same measured stock convention and as-of timestamp. |
| `forecast_demand` | float / decimal | forecast output | Refer to the aligned forecast period. |
| `stock_out_risk_level` | string | **derived** | Controlled label defined by the risk module (for example, high/medium/low only if adopted). |
| `stock_out_risk_score` | float | **derived**, optional | Only where a future risk method defines it. |
| `risk_period_start`, `risk_period_end` | datetime64 / date | **derived** | Period to which the assessment applies. |

## MCA product-prioritization interface: prescriptive analytics → UI

| Field | Type | Origin | Convention |
|---|---|---|
| `sku` | string | canonical data | Primary identifier. |
| `mca_score` | float | **derived** | Composite score from a separately documented approved MCA method. |
| `priority_rank` | integer | **derived** | Rank based on the documented sort/tie rule. |
| `priority_label` | string | **derived** | Human-readable priority outcome, if defined by the MCA module. |
| `mca_method_version` | string | **derived** | Version/identifier for reproducibility. |

This contract defines no MCA weights, normalization method, or scoring formula.

## Replenishment recommendation interface: prescriptive analytics → UI

| Field | Type | Origin | Convention |
|---|---|---|
| `sku` | string | canonical data | Primary identifier. |
| `raw_product_name` | string | canonical data | Original product name retained for traceability. |
| `standardized_product_name` | string | canonical/derived data | Optional display name, distinct from raw name. |
| `current_stock` | integer / decimal | inventory input | Stock with as-of timestamp. |
| `forecast_demand` | float / decimal | forecast output | Demand for stated forecast horizon. |
| `stock_out_risk_level` | string | risk output | Risk label with source period. |
| `recommended_quantity` | integer / decimal | **derived** | Proposed amount from a future approved prescriptive rule; never an automatic order. |
| `recommendation_status` | string | **derived** | Review-oriented status/label from the prescriptive module. |
| `recommendation_reason` | string | **derived** | Concise traceable explanation supplied by the responsible module. |

The UI presents recommendations for business-owner review only. It does not purchase inventory, place orders, or modify Shopee data.

## Handoff requirements

Each producing module must provide: contract version, processing timestamp, source/period coverage, field definitions for any additional derived columns, explicit missing-data behavior, and a validation summary. Each consuming module must show an insufficient-data/unsupported state instead of fabricating values when its required fields are unavailable.
