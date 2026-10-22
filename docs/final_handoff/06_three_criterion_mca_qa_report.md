# Three-Criterion MCA QA Report

## 1. Executive Summary

This report documents the quality assurance and methodology compliance audit of the **Three-Criterion Multi-Criteria Analysis (MCA)** implementation on branch `week4-integrated`. The three-criterion MCA replaces legacy 5- and 6-criterion models that relied on unverified assumptions, delivering a mathematically sound, TA-approved decision support engine for SKU prioritization.

---

## 2. Transition from Legacy Criteria to Approved Three-Criterion Model

### 2.1. Why Legacy Criteria Were Deprecated
Earlier iterations considered five or six criteria (including *Profit Margin*, *Supplier Lead Time*, and *Stock-Out Frequency*). These were deprecated following technical advisor evaluation:
1. **Profit Margin**: Shopee transaction exports do not contain reliable, verified cost-of-goods-sold (COGS) or procurement invoices. Imputing profit margins introduced ungrounded assumptions.
2. **Supplier Lead Time**: Supplier procurement lead times are external to Shopee Seller Centre records.
3. **Stock-Out Frequency**: Historical daily stock snapshots were not captured continuously across the historical period.

### 2.2. The Approved Three Criteria
The approved model evaluates SKUs exclusively across three empirical, verifiable dimensions:

| Criterion Name | Empirical Source | Direction / Type | Business Objective |
| :--- | :--- | :--- | :--- |
| **Sales Velocity** | Transaction History / Fact Sales | **Benefit** ($+$) | Prioritize fast-moving, high-turnover SKUs |
| **Forecasted Demand** | SKU Demand Forecast Engine | **Benefit** ($+$) | Prioritize SKUs with high upcoming consumer demand |
| **Recorded Return/Refund Quantity Rate** | Return/Refund Review Store | **Cost** ($-$) | Penalize high defect / refund rates; prioritize reliable products |

---

## 3. Approved Weighting & Sensitivity Scenarios

### 3.1. Approved Equal-Thirds Baseline
The approved baseline allocates equal weight across the three criteria:
- **Sales Velocity**: $\frac{1}{3} \approx 33.333\%$
- **Forecasted Demand**: $\frac{1}{3} \approx 33.333\%$
- **Recorded Return/Refund Quantity Rate**: $\frac{1}{3} \approx 33.334\%$
$$\sum w_j = 1.0000$$

### 3.2. Alternative Weight Sensitivity Scenario (Volume & Quality)
For stress testing and sensitivity analysis, the system evaluates an alternative scenario:
- **Sales Velocity**: $25.0\%$
- **Forecasted Demand**: $25.0\%$
- **Recorded Return/Refund Quantity Rate**: $50.0\%$
*(Higher emphasis placed on product quality and customer satisfaction).*

Sensitivity rankings and score shifts can be compared and downloaded directly via `Download weight comparison`.

---

## 4. Return/Refund Evidence Integration & Coverage Protocol

### 4.1. Request-Date Coverage vs. Order Dates
- Shopee return/refund requests occur after the order date.
- The system enforces explicit **Request-Date Coverage** parameters (`request_start`, `request_end`, `export_start`, `export_end`).
- If an order occurred within the sales assessment window but the return window extends beyond the available return export, the system flags coverage explicitly rather than assuming zero returns.

### 4.2. Dispute Re-Evaluation on Refresh
- Disputed return/refund records (e.g., cases under seller appeal or platform review) are tracked in the SQLite review store.
- When an updated return/refund export is uploaded, pending disputes are re-assessed against the latest decision status (*Request Refunded*, *Refund Approved*, *Dispute Rejected*).
- Decisions transition deterministically without erasing prior audit logs.

---

## 5. SKU Eligibility, Normalization & Audit Trail

### 5.1. Handling Incomplete SKUs
Only SKUs with complete, valid measurements across all three criteria receive a composite MCA score:
- If a SKU has missing return evidence or is outside forecast eligibility, it is excluded from final ranking.
- The reason for exclusion is logged in the `mca_audit` table (e.g., `Missing return/refund coverage`, `No eligible forecast`).
- No arbitrary defaults (e.g., 0% return rate or mean demand) are invented to force a score.

### 5.2. Verification of User Interface & Downloads
- **Readiness Audit Table**: Rendered when audit evidence is present, complete with formatted values and `Download MCA readiness audit` CSV export.
- **Rankings Table**: Rendered with exact composite scores, criteria contributions, and `Download MCA rankings` CSV export.
- **Download Equality**: Automated tests (`test_three_criterion_mca.py`, `test_synthetic_mca_staging.py`) confirm that the downloaded CSV files match the backend calculated DataFrames at full precision with zero truncation.
