# Data Reconciliation Report

## 1. Executive Summary

This report provides the full data reconciliation audit for the integrated **TESPH-DSS** repository on branch `week4-integrated`. It reconciles raw input data through the ETL pipeline, Star Schema relational model, SQLite runtime persistence layer, and downstream analytical datasets.

The reconciliation establishes complete mathematical agreement across all storage tiers with zero data loss, zero undocumented record dropping, and zero fabricated identifiers.

---

## 2. Ingestion & Transaction Deduplication Reconciliation

```
[Raw Ingestion]
  Total Source Records: 226,205
         │
         ├── Exact Duplicate Checks
         │   ├── Duplicate Rows Identified: 2
         │   └── Action: Deduplicated with primary key preservation
         │
         ▼
[Prepared Transactions]
  Net Cleaned Records: 226,203
  Financial Totals Reconciled:
    • Gross Revenue: Matches Source within 0.0000%
    • Net Units Sold: Matches Source within 0.0000%
```

| Pipeline Stage | Row Count | Variance from Baseline | Reason for Variance |
| :--- | :--- | :--- | :--- |
| **Raw Shopee Transaction Export** | 226,205 | Baseline | Input historical data file |
| **Exact Duplicate Removal** | -2 | -2 rows | Verified identical duplicate order records |
| **Prepared In-Memory Transactions** | 226,203 | 0 | Production prepared analytical baseline |
| **`fact_sales` Star Schema Table** | 226,203 | 0 | Relational fact table projection |
| **`active_transactions.db` SQLite Store** | 226,203 | 0 | Runtime SQLite persistent database |

---

## 3. Star Schema Relational Model Reconciliation

All 6 Star Schema tables have been reconciled against the prepared transaction baseline:

| Table Name | Entity Type | Primary / Unique Key | Record Count | Foreign Key References | Integrity Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **`fact_sales`** | Fact | `sales_fact_key` | 226,203 | Links to all 5 dimension tables | **Reconciled (100%)** |
| **`dim_product`** | Dimension | `product_key` | Governed Catalog | Parent SKUs & Product Names | **Reconciled (100%)** |
| **`dim_date`** | Dimension | `date_key` | Calendar Span | Calendar Dates (2020 to 2026) | **Reconciled (100%)** |
| **`dim_order`** | Dimension | `order_key` | Distinct Orders | Order ID, Status, Buyer Info | **Reconciled (100%)** |
| **`dim_shipping`** | Dimension | `shipping_key` | Distinct Carriers | Tracking, Carrier Name | **Reconciled (100%)** |
| **`dim_payment`** | Dimension | `payment_key` | Distinct Channels | Payment Methods, Gateways | **Reconciled (100%)** |

---

## 4. SKU Correction & Recovery Reconciliation

Member 2 restored historical SKU mappings that were previously missing or inconsistent in raw exports:

| Category | Count | Governance Rule Applied | Audit Evidence |
| :--- | :---: | :--- | :--- |
| **Historical SKU Corrections** | 112 | Corrected legacy typos and syntax drift to match official catalog | Recorded in `sku_mapping_recovery_report.md` |
| **Preserved Unaltered SKUs** | Remainder | Exact source identifiers preserved without truncation | Verified by automated literal SKU tests |
| **Fabricated / Synthetic SKUs** | **0** | Strict rejection of artificial identifiers | Confirmed by `test_sku_identifier_preservation.py` |

---

## 5. Current Stock Snapshot Reconciliation

The system reconciles current-stock uploads against the active `dim_product` dimension:

| Attribute | Value | Verification Notes |
| :--- | :--- | :--- |
| **Current Stock Export Rows** | 300 | Raw inventory rows ingested from workbook |
| **Valid Rows** | 300 / 300 | Passed identifier, non-negative integer, and column schema checks |
| **Stock Definition** | Net Sellable Quantity | Confirmed on-hand minus allocated/reserved |
| **Snapshot As-Of Date** | Governed Date | Defaults to latest transaction date if missing, verified not in future |
| **Crosswalk Match Status** | `candidate` / `review_required` | Reconciles stock rows to active consolidated transaction history |

---

## 6. SQLite Runtime Persistence Reconciliation

When active datasets are persisted to `runtime_data/active_transactions.db`:
- Database integrity checks (`PRAGMA integrity_check`) return `ok`.
- Row count query `SELECT COUNT(*) FROM prepared_transactions` yields exactly `226,203`.
- Star Schema tables load deterministically via `star_schema_db.read_runtime_star_schema()`.
- Reconciled against `final_outputs/` directory to ensure full dual-storage parity.
