"""Legacy methodology parameters and explicit Week 2 configuration.

Existing descriptive constants retain the earlier project's definitions.
ForecastConfig implements TA constraints with documented team defaults.
Client approval is distinct from evidence of current-catalog activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


# ---------------------------------------------------------------------------
# 1. Revenue and Demand Definitions
# ---------------------------------------------------------------------------
GROSS_REVENUE_COLUMN = "Total Buyer Payment"
DEMAND_DEFINITION = "gross_demand"  # Completed + Returned/Refunded

# ---------------------------------------------------------------------------
# 2. Descriptive Analytics — Sales Trends
# ---------------------------------------------------------------------------
TREND_FREQUENCY = "M"  # Monthly

# ---------------------------------------------------------------------------
# 3. Product Movement and Low-Sales Identification (KAN-36, KAN-38)
# ---------------------------------------------------------------------------
MOVEMENT_FREQUENCY = "M"  # Monthly
MOVEMENT_RECENT_PERIODS = 3  # Latest 3 complete months

# Movement classification thresholds:
# 3 positive-demand months → Fast Moving
# 2 positive-demand months → Regular Moving
# 1 positive-demand month  → Slow Moving
# 0 positive-demand months → No Movement
MOVEMENT_FAST_MIN_POSITIVE_PERIODS = 3
MOVEMENT_REGULAR_MIN_POSITIVE_PERIODS = 2

# Low-sales: at or below 25th percentile of positive recent demand per category
LOW_SALES_PERCENTILE = 25  # Used to compute the threshold dynamically

# ---------------------------------------------------------------------------
# 4. Forecasting — Dataset Preparation (KAN-41)
# ---------------------------------------------------------------------------
FORECAST_FREQUENCY = "D"  # Team decision: daily operational demand
FORECAST_DEMAND_DEFINITION = "gross_demand"

# ---------------------------------------------------------------------------
# 5. Forecasting — Horizon (KAN-42)
# ---------------------------------------------------------------------------
FORECAST_HORIZON = 7  # Team decision: next seven daily periods

# ---------------------------------------------------------------------------
# 6. Forecasting — Model Parameters (KAN-43, KAN-44, KAN-45, KAN-46)
# ---------------------------------------------------------------------------
MA_WINDOW = 3  # Moving Average: 3-month window

# Exponential Smoothing: grid search alpha from 0.1 to 0.9
ES_ALPHA_CANDIDATES = [round(0.1 * i, 1) for i in range(1, 10)]

# Seasonal Index Adjustment: 12-month cycle
SEASONAL_CYCLE = 12

# ---------------------------------------------------------------------------
# 7. Forecast Validation and Model Selection (KAN-47 to KAN-50, KAN-53)
# ---------------------------------------------------------------------------
VALIDATION_PERIODS = 14  # Latest 14 feasible rolling origins
PRIMARY_SELECTION_METRIC = "MAPE"  # TA instruction, September 11
SECONDARY_SELECTION_METRIC = "RMSE"
MAPE_ZERO_ACTUAL_POLICY = "denominator_floor"  # Team decision: adjusted MAPE

# ---------------------------------------------------------------------------
# 8. Forecast Output (KAN-53)
# ---------------------------------------------------------------------------
FORECAST_AGGREGATION = "sum"  # Single value for 1-month horizon

# ---------------------------------------------------------------------------
# 9. Category Eligibility and Selection (KAN-51)
# ---------------------------------------------------------------------------
CATEGORY_ASSESSMENT_WINDOW = 24  # Latest 24 complete months
MINIMUM_HISTORY_PERIODS = 24  # At least 24 months total
MINIMUM_COMPLETENESS = 18 / 24  # 0.75
MINIMUM_CONSISTENCY = 18 / 24  # 0.75
DEMAND_CONTRIBUTION_WEIGHT = 0.50
REVENUE_CONTRIBUTION_WEIGHT = 0.50
MAX_FORECAST_CATEGORIES = 3

# ---------------------------------------------------------------------------
# 10. Stock-Out Risk (KAN-54)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StockRiskConfig:
    """DOI bands aligned to immediate, near-term, and forecast-horizon exposure."""
    critical_max_days: float = 1.0
    high_max_days: float = 3.0
    medium_max_days: float = float(FORECAST_HORIZON)

    def validate(self) -> None:
        values = [
            self.critical_max_days,
            self.high_max_days,
            self.medium_max_days,
        ]
        if any(not isfinite(float(value)) or float(value) < 0 for value in values):
            raise ValueError("Stock-risk thresholds must be finite and non-negative")
        if not self.critical_max_days < self.high_max_days < self.medium_max_days:
            raise ValueError("DOI thresholds must increase from Critical to High to Medium")


STOCK_RISK_THRESHOLDS = StockRiskConfig()
RISK_INDEX_FORMULA = "uncovered_horizon_demand_share"
RISK_INDEX_ZERO_DEMAND_VALUE = 0.0
RISK_INDEX_MISSING_STOCK_VALUE = float("nan")

# Shopee transaction exports do not provide supplier lead times or review
# cadence. These are transparent system-level defaults, never SKU-level facts.
@dataclass(frozen=True)
class ReplenishmentConfig:
    supplier_lead_time_days: int = 7
    review_period_days: int = 7
    safety_stock_days: int = 1
    max_stock_age_days: int = 90

    def validate(self) -> None:
        for name in (
            "supplier_lead_time_days",
            "review_period_days",
            "safety_stock_days",
            "max_stock_age_days",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.supplier_lead_time_days < 1 or self.max_stock_age_days < 1:
            raise ValueError("Lead time and maximum stock age must be positive")


REPLENISHMENT_CONFIG = ReplenishmentConfig()


@dataclass(frozen=True)
class ForecastConfig:
    """Daily operational defaults; team choices are recorded in the handoff."""

    frequency: str = FORECAST_FREQUENCY
    horizon: int = FORECAST_HORIZON
    validation_periods: int = VALIDATION_PERIODS
    tuning_periods: int = 7
    minimum_training_periods: int = 37
    ma_windows: tuple[int, ...] | None = None
    es_alphas: tuple[float, ...] = tuple(ES_ALPHA_CANDIDATES)
    mape_zero_policy: str = MAPE_ZERO_ACTUAL_POLICY
    mape_denominator_floor: float | None = 1.0
    primary_metric: str = PRIMARY_SELECTION_METRIC
    secondary_metric: str = SECONDARY_SELECTION_METRIC
    approval_reference: str = "TA Sep 11/14; team implementation decisions in docs/week2_handoff.md"

    @property
    def windows(self) -> tuple[int, ...]:
        if self.ma_windows is not None:
            return self.ma_windows
        return (3, 7, 14, 30) if self.frequency == "D" else (2, 3, 6, 12)

    def validate(self) -> None:
        if self.frequency not in {"D", "M"}:
            raise ValueError("Week 2 forecast frequency must be D or M")
        if not isinstance(self.approval_reference, str):
            raise ValueError("approval_reference must be a string")
        for name in ("horizon", "validation_periods", "tuning_periods", "minimum_training_periods"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.minimum_training_periods < 3:
            raise ValueError("minimum_training_periods must be at least 3 for nested tuning")
        if not self.windows or any(isinstance(w, bool) or not isinstance(w, int) or w < 1 for w in self.windows):
            raise ValueError("Moving Average windows must be positive integers")
        if not self.es_alphas or any(not isfinite(a) or not 0 < a <= 1 for a in self.es_alphas):
            raise ValueError("ES alphas must be finite and in (0, 1]")
        if min(self.windows) >= self.minimum_training_periods:
            raise ValueError("At least one MA window must allow inner holdout validation")
        if self.mape_zero_policy not in {"return_nan", "denominator_floor"}:
            raise ValueError("Week 2 MAPE must retain zero-demand observations")
        if self.mape_zero_policy == "denominator_floor":
            if self.mape_denominator_floor is None or not isfinite(self.mape_denominator_floor) or self.mape_denominator_floor <= 0:
                raise ValueError("A positive finite MAPE denominator floor is required")
        if (self.primary_metric, self.secondary_metric) != ("MAPE", "RMSE"):
            raise ValueError("TA model selection requires MAPE first, then RMSE")

# ---------------------------------------------------------------------------
# 11. Multi-Criteria Analysis (MCA)
# ---------------------------------------------------------------------------
MCA_CRITERIA = (
    "Sales Velocity",
    "Gross Revenue",
    "Supplier Lead Time",
    "Projected Stock-Out Risk",
    "Forecasted Demand",
    "Return Rate",
)

MCA_DIRECTIONS = {
    "Sales Velocity": "benefit",
    "Gross Revenue": "benefit",
    "Supplier Lead Time": "cost",
    "Projected Stock-Out Risk": "cost",
    "Forecasted Demand": "benefit",
    "Return Rate": "cost",
}

# No stakeholder-elicited or empirical evidence currently supports unequal
# influence, so use equal weights until a documented review justifies otherwise.
MCA_WEIGHT_RATIONALE = (
    "Equal weights are a transparent neutral baseline; no documented stakeholder "
    "or empirical evidence supports privileging one criterion."
)
MCA_WEIGHTS = {criterion: 1 / len(MCA_CRITERIA) for criterion in MCA_CRITERIA}

MCA_HIGH_PRIORITY_MIN = 2 / 3
MCA_MEDIUM_PRIORITY_MIN = 1 / 3
