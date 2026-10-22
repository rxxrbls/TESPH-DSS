# Calculation Validation Report

## 1. Executive Summary

This report validates the mathematical, statistical, and operational formulas implemented across the **TESPH-DSS** analytical pipeline on branch `week4-integrated`. Every calculation has been audited against documented mathematical specifications and verified through deterministic unit and integration tests.

---

## 2. Descriptive Analytics Calculations

### 2.1. Revenue & Demand Formulations
- **Gross Revenue**:
  $$\text{Gross Revenue} = \sum (\text{Quantity} \times \text{Unit Deal Price})$$
- **Net Revenue After Returns**:
  $$\text{Net Revenue} = \text{Gross Revenue} - \text{Returned Revenue}$$
- **Return Quantity Rate**:
  $$\text{Return Quantity Rate} = \frac{\sum \text{Returned Units}}{\sum \text{Gross Units Sold}} \times 100\%$$
- **Sales Velocity**:
  $$\text{Sales Velocity} = \frac{\sum \text{Net Units Sold in Assessment Window}}{\text{Total Days in Assessment Window}}$$

---

## 3. Demand Forecasting Calculations & Accuracy Metrics

### 3.1. Forecasting Models
The system evaluates multiple forecasting candidates per eligible SKU:
1. **Simple Moving Average (SMA)**:
   $$\hat{y}_{t+1} = \frac{1}{k} \sum_{i=0}^{k-1} y_{t-i}$$
2. **Exponential Smoothing (SES)**:
   $$\hat{y}_{t+1} = \alpha y_t + (1 - \alpha) \hat{y}_t, \quad \alpha \in (0, 1)$$
3. **Linear Trend**:
   $$\hat{y}_t = \beta_0 + \beta_1 t$$
4. **Croston's Method (Intermittent Demand)**:
   Separates non-zero demand size from inter-arrival intervals.

### 3.2. Forecast Accuracy Evaluation Metrics
Accuracy metrics are computed over an out-of-sample holdout test window:
- **Mean Absolute Error (MAE)**:
  $$\text{MAE} = \frac{1}{n} \sum_{t=1}^n |y_t - \hat{y}_t|$$
- **Root Mean Squared Error (RMSE)**:
  $$\text{RMSE} = \sqrt{\frac{1}{n} \sum_{t=1}^n (y_t - \hat{y}_t)^2}$$
- **Mean Absolute Percentage Error (MAPE)**:
  $$\text{MAPE} = \frac{100\%}{n} \sum_{t=1}^n \left| \frac{y_t - \hat{y}_t}{y_t} \right| \quad (\text{for } y_t \neq 0)$$
- **Coefficient of Determination ($R^2$)**:
  $$R^2 = 1 - \frac{\sum (y_t - \hat{y}_t)^2}{\sum (y_t - \bar{y})^2}$$
  *Note: Handled gracefully as undefined/N/A when actual values are constant ($\text{variance} = 0$).*

---

## 4. Stock-Out Risk Calculations

### 4.1. Days of Inventory (DOI)
$$\text{DOI} = \frac{\text{Current Net Sellable Stock}}{\text{Average Daily Forecasted Demand}}$$

### 4.2. Risk Classification Thresholds
- **Critical Risk**: $\text{DOI} \le \text{Lead Time}$ (Stock runs out before an order can arrive).
- **High Risk**: $\text{Lead Time} < \text{DOI} \le \text{Lead Time} + \text{Safety Buffer}$.
- **Medium Risk**: $\text{Lead Time} + \text{Safety Buffer} < \text{DOI} \le \text{Reorder Point Threshold}$.
- **Low Risk**: $\text{DOI} > \text{Reorder Point Threshold}$ (Stock level is healthy).

---

## 5. Multi-Criteria Analysis (MCA) Normalization

The approved three criteria are normalized using Min-Max scaling:

### 5.1. Benefit Criteria (Sales Velocity, Forecasted Demand)
Higher values indicate greater prioritization urgency:
$$S_{ij} = \frac{x_{ij} - x_{\min, j}}{x_{\max, j} - x_{\min, j}}$$

### 5.2. Cost Criteria (Recorded Return/Refund Quantity Rate)
Lower return rates indicate higher quality / customer satisfaction:
$$S_{ij} = \frac{x_{\max, j} - x_{ij}}{x_{\max, j} - x_{\min, j}}$$

### 5.3. Constant Criterion & Edge-Case Protection
- **Constant Criterion** ($x_{\max, j} = x_{\min, j}$): Normalized value is set to **$0.5$** to avoid division by zero and maintain mathematical neutrality.
- **Missing / Unresolved Criteria**: The SKU is excluded from final composite ranking and logged in `mca_audit` with the explicit reason.

### 5.4. Composite Priority Score
Using approved equal-thirds baseline weights ($w_1 = \frac{1}{3}, w_2 = \frac{1}{3}, w_3 = \frac{1}{3}$):
$$\text{SKU Priority Score}_i = \sum_{j=1}^3 w_j S_{ij}$$

---

## 6. Replenishment Recommendations Calculations

### 6.1. Safety Stock ($SS$)
$$SS = Z \times \sigma_{LT} = Z \times \sqrt{L \cdot \sigma_D^2 + D^2 \cdot \sigma_L^2}$$
*(Where $Z = 1.645$ for a 95% service level standard).*

### 6.2. Target Stock Level ($TSL$)
$$TSL = (\text{Forecast Daily Demand} \times (\text{Lead Time} + \text{Review Period})) + SS$$

### 6.3. Recommended Replenishment Quantity ($Q_{\text{rec}}$)
$$Q_{\text{rec}} = \max(0, \lceil TSL - \text{Current Stock} - \text{On Order} \rceil)$$

### 6.4. Lead Time Fallbacks
When supplier-specific lead times are unconfigured, the system applies the governed default lead time (e.g., 7 days) and displays a clear disclaimer alerting the operator that catalog fallback parameters were utilized.
