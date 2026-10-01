# Physical Star Schema Database

## Overview
The active Star Schema is persisted in the local SQLite database
`runtime_data/active_transactions.db`. It is rebuilt from reconciled active
prepared transactions and published atomically with that same prepared dataset.
Historical `final_outputs/*.csv` files remain immutable governed Member 1
handoff artifacts.
SQLite was chosen as the database engine due to its zero-configuration footprint, embedded nature, and excellent support within Python.

## Load Order
To properly enforce foreign key constraints, the tables must be loaded in a specific order:
1. `dim_product`
2. `dim_date`
3. `dim_order`
4. `dim_shipping`
5. `dim_payment`
6. `fact_sales` (references the above dimensions)

The six tables above are the materialized Star Schema. The same runtime
database also stores `prepared_transactions` as the denormalized active
handoff, together with runtime metadata and ingestion-batch audit records.
The compact audit ledger stores one row per distinct content-derived batch ID,
not one row per upload attempt. A successfully reconciled zero-new-row batch
is recorded without replacing the analytical snapshot; repeated identical
content reuses its first audit row.

## DDL and Constraints
The database uses `PRAGMA foreign_keys = ON` to enforce relational integrity.

- **Primary Keys**: Each dimension has a primary key (e.g. `product_key`, `date_key`, `"Order ID"`).
- **Foreign Keys**: `fact_sales` holds foreign keys referencing all dimensions.
- **Constraints**: Enforced on the application layer via `star_schema_db.py`.

## Validation
Validation checks run via `validate_star_schema_db.py` to ensure:
- Primary key uniqueness across all tables.
- Zero orphan rows in `fact_sales`.

## Replacement and reconciliation

A candidate database is fully written and validated for schema, SQLite types,
row counts, database integrity, and foreign keys before an atomic replacement
of the live database. Failed writes or validation preserve the previous valid
snapshot. Tests reconcile SQLite against the `ETLResult` from the same ETL run,
not against historical CSV outputs.

The application is designed for local/single-operator capstone use. Concurrent
sessions are not guaranteed one consistent dataset: a later upload can replace
the global SQLite snapshot while an existing session retains its own in-memory
`ETLResult`.
