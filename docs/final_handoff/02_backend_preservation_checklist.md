# Backend Preservation Checklist

## 1. Objective

This checklist verifies that 100% of the analytical, architectural, and data engineering achievements delivered by Member 2 (`origin/sab-week3`, commit `51c3d0c`) have been preserved without omission or distortion in `week4-integrated`.

---

## 2. Preservation Verification Matrix

| Category | Verification Item | Target Standard | Integrated Verification Result | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Data Ingestion** | Raw Transaction Rows | 226,205 rows ingested from official baseline | Verified 226,205 raw transactions loaded in ETL tests | **PASS** |
| **Data Ingestion** | Prepared Transactions | 226,203 rows after exact-duplicate removal | Exactly 226,203 prepared transaction rows verified | **PASS** |
| **Data Ingestion** | Exact Duplicates Deduplicated | Exactly 2 redundant records removed | Deduplication logs and tests confirm exactly 2 rows removed | **PASS** |
| **Catalog Governance** | SKU Corrections | Exactly 112 SKU reference corrections | Exactly 112 SKU mappings verified in `sku_mapping_recovery_report.md` | **PASS** |
| **Catalog Governance** | Zero SKU Fabrication | No invented, hallucinated, or placeholder SKUs | Automated audit confirms zero manufactured SKU identifiers | **PASS** |
| **Star Schema** | Relational Dimensional Model | 6 core tables: `fact_sales`, `dim_product`, `dim_date`, `dim_order`, `dim_shipping`, `dim_payment` | All 6 tables verified with referential integrity | **PASS** |
| **Database Persistence** | Runtime SQLite Engine | `runtime_data/active_transactions.db` table generation & recovery | Database creation, caching, and state restoration verified | **PASS** |
| **Forecasting** | Strict Validation Holdout Date | Calendar holdout date equality validation | Enforced in `sku_forecasting.py` line 150+ | **PASS** |
| **Forecasting** | Accuracy Evaluation Metrics | `MAE`, `RMSE`, `MAPE`, `R²` calculation per eligible SKU | Displayed in `render_forecast_accuracy` on Demand Forecast page | **PASS** |
| **Prescriptive Engine** | Approved MCA Criteria Count | Exactly 3 criteria: Sales Velocity, Forecasted Demand, Recorded Return/Refund Quantity Rate | Obsolete 5/6 criteria fully purged from active scoring | **PASS** |
| **Prescriptive Engine** | MCA Baseline Weights | Equal-Thirds (33.33% / 33.33% / 33.34%) | Approved baseline active; sensitivity comparison available | **PASS** |
| **Prescriptive Engine** | Return/Refund Review Store | Request-date coverage separation from order dates | Handled via `three_criterion_mca.Coverage` and SQLite review store | **PASS** |
| **Prescriptive Engine** | Dispute Re-evaluation | Unresolved disputes re-evaluated upon subsequent refresh | Verified in `tests/test_three_criterion_mca.py` | **PASS** |
| **Prescriptive Engine** | Replenishment Lead Time | Catalog fallback handling when Supplier Lead Time missing | Warning displayed and lead time source column provided | **PASS** |
| **Performance** | Lazy-Load State Optimization | `include_forecast=False`, `include_analytics=False` | Applied across Dashboard, Sales Analytics, and Risk pages | **PASS** |

---

## 3. Detailed Verification Notes

### 3.1. Row Count & SKU Reconciliation Integrity
- Ingestion pipeline executed against `active_transactions.db` and baseline CSV exports.
- **Raw Row Count**: 226,205.
- **Prepared Transaction Rows**: 226,203.
- **SKU Corrections**: 112 recorded catalog variations mapped to stable parent products without altering transaction keys.
- **Integrity Rule**: No fallback data was synthesized to force populated states where genuine data is absent.

### 3.2. Three-Criterion MCA Engine
- Criteria implemented in `three_criterion_mca.py` and `prescriptive_calculations.py`:
  1. **Sales Velocity** ($\text{Units/Day}$): Benefit criterion ($+$ direction), Min-Max normalized.
  2. **Forecasted Demand** ($\text{Units}$): Benefit criterion ($+$ direction), Min-Max normalized.
  3. **Recorded Return/Refund Quantity Rate** ($\%$): Cost criterion ($-$ direction), inverted Min-Max normalized.
- Constant criteria default score: $0.5$ (preserving mathematical stability).
- Missing criteria rule: SKU excluded from final ranking with explicit audit reason recorded in `mca_audit`.

### 3.3. Dispute Resolution and Audit Trail
- The SQLite review store maintains an append-only audit trail of batch processing events.
- Disputed return/refund rows that are Under Review or Disputed are flagged, and upon a subsequent refresh batch, their decision statuses are re-evaluated rather than frozen.

### 3.4. Test Suite Confirmation
- All 432 backend-specific tests inherited from `origin/sab-week3` continue to pass without a single failure or modification to backend math.
