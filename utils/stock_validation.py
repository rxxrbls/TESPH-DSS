"""Stock As-Of Date validation."""
from datetime import date
from methodology_config import REPLENISHMENT_CONFIG

STOCK_RECENCY_THRESHOLD_DAYS = REPLENISHMENT_CONFIG.max_stock_age_days


def validate_stock_as_of(
    stock_date: date | None,
    threshold_days: int = STOCK_RECENCY_THRESHOLD_DAYS,
) -> dict:
    """Validate the stock as-of date.
    
    Returns dict with:
        valid: bool — True if date is acceptable (not None, not future)
        issues: list[str] — warning/error messages
        is_stale: bool — True if data is older than threshold_days
    """
    if stock_date is None:
        return {"valid": False, "issues": ["Stock As-Of Date is required"], "is_stale": False}
    
    issues = []
    if stock_date > date.today():
        issues.append("Stock As-Of Date cannot be in the future")
        return {"valid": False, "issues": issues, "is_stale": False}
    
    days_old = (date.today() - stock_date).days
    is_stale = days_old > threshold_days
    if is_stale:
        issues.append(
            f"Stock data is {days_old} days old (threshold: {threshold_days} days). "
            f"Consider re-exporting from Shopee Seller Centre for accurate stock levels."
        )
    
    return {"valid": True, "issues": issues, "is_stale": is_stale}
