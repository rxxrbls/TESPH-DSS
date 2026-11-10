"""Stock As-Of Date validation."""
from datetime import date, datetime
import re
from methodology_config import REPLENISHMENT_CONFIG

STOCK_RECENCY_THRESHOLD_DAYS = REPLENISHMENT_CONFIG.max_stock_age_days


def snapshot_date_from_filename(filename: str, *, today: date | None = None) -> date | None:
    """Extract a real, non-future YYYY-MM-DD or YYYY_MM_DD snapshot date."""
    current_date = today or date.today()
    match = re.search(r"(?<!\d)(\d{4}[-_]\d{2}[-_]\d{2})(?!\d)", filename)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group(1).replace("_", "-"), "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed <= current_date else None


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
