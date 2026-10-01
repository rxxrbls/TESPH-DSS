# ETL Integration Guide

## Overview
This document describes the integration between the Streamlit frontend (`pages/data_upload.py`) and the underlying ETL pipeline (`etl.py`, `final_etl_handoff.py`). The orchestrator (`etl_streamlit.py`) handles the execution flow without writing intermediate datasets to disk, passing all data entirely in-memory via `st.session_state`.

## Architecture
The `run_etl_from_upload` function acts as the bridge:
1. **Frontend**: The user uploads a Shopee export in `pages/data_upload.py`.
2. **Orchestrator**: The bytes are converted to a temporary file path (`_bytes_to_temp_path`) and passed to `etl.py` extraction functions.
3. **Execution**: Step-by-step progress is streamed back to Streamlit using the `on_step` callback.
4. **Handoff**: The transformed data is structured into Star Schema format using `build_star_schema_tables`.
5. **Reconciliation**: Validated staging data is compared with the active
   historical authority using filename-independent exact-content fingerprints.
6. **Persistence**: Consolidated prepared transactions, their derived Star
   Schema, and an ingestion summary are atomically published to
   `runtime_data/active_transactions.db`, then stored in session state.

## Pipeline Steps
The orchestrator executes 5 strict phases:
1. **Ingest**: File reading (`extract_file`), format inference, and initial DataFrame creation.
2. **Clean**: Identifying exact duplicate rows and mapping missing values (`detect_exact_duplicates`, `detect_missing_values`).
3. **Validate**: Type checking numeric/date fields and assessing financial values (`validate_data_types`).
4. **Transform**: Normalizing data into five dimension tables, one fact table, and a wide `prepared_transactions` view.
5. **Load**: Verifying the output schemas match the frozen `FINAL_SCHEMAS` contract and persisting the results in `st.session_state` and SQLite DB.

## Session State Contract
The central hub for sharing data is `utils/state.py`:
- `data_status`: Enum (`NO_DATA`, `PROCESSING`, `DATA_READY`).
- `star_schema`: `dict[str, pd.DataFrame]` of normalized tables.
- `prepared_transactions`: `pd.DataFrame` containing the denormalized dataset.
- `etl_validation_report`: Full `ETLValidationReport` dataclass detailing data quality.
- `inventory_data`: Raw inventory `pd.DataFrame`.
- `inventory_crosswalk`: Mapped crosswalk DataFrame with `dim_product`.
- `inventory_validation`: Validation result mapping.

Downstream apps use getters (e.g. `get_star_schema()`) only if `get_data_status() == DataStatus.DATA_READY`.

## Error Handling
Failures across the ETL stack are caught by `etl_streamlit.py` and mapped to human-readable strings via `utils/etl_errors.py`. 
Streamlit handles these natively using standard components (e.g., `st.error`, `st.expander`), never exposing raw exceptions to the end user.

## Star Schema Tables
- `fact_sales`: Transactional grain; references dimensions.
- `dim_product`: Unique products and variations.
- `dim_date`: Temporal context.
- `dim_order`: Order-level characteristics.
- `dim_shipping`: Logistics metrics.
- `dim_payment`: Payment metrics.
- `prepared_transactions`: 76-column denormalized view.

## Database Integration

`final_outputs/prepared_transactions.csv` is read-only governed history. The
runtime database at `runtime_data/active_transactions.db` is bootstrapped from
that baseline and receives only reconciled additions. It persists consolidated
prepared data, six Star-Schema tables, metadata, and ingestion summaries in one
atomically replaced SQLite snapshot. Failed validation, reconciliation, or
database publication cannot replace the previous snapshot.

## Stock Data Integration
Inventory sheets are processed via `etl_inventory.py`. A valid Stock As-Of Date is mandatory. The inventory is crosswalked against `dim_product` (only available if `DATA_READY`), tracking available SKUs, mismatched values, and identifying items nearing their threshold.
