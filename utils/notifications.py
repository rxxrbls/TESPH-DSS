"""Lightweight in-app notification system for TESPH DSS.

Generates real notifications from actual system events only.
Does not fabricate alerts, does not trigger analytical reruns.
Persists notifications in session_state to avoid rerun duplicates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import streamlit as st

LOGGER = logging.getLogger(__name__)


# Notification category keys used in preferences
PREF_UPLOAD_UPDATES = "notif_pref_upload_updates"
PREF_DATA_FRESHNESS = "notif_pref_data_freshness"
PREF_CRITICAL_RISK = "notif_pref_critical_risk"

# Export format preference
PREF_EXPORT_FORMAT = "pref_export_format"

# Stock recency threshold (days)
PREF_STOCK_RECENCY_DAYS = "pref_stock_recency_days"


def _default_prefs() -> dict[str, Any]:
    return {
        PREF_UPLOAD_UPDATES: True,
        PREF_DATA_FRESHNESS: True,
        PREF_CRITICAL_RISK: True,
        PREF_EXPORT_FORMAT: "CSV (.csv)",
        PREF_STOCK_RECENCY_DAYS: 90,
    }


def initialize_notifications() -> None:
    """Ensure notification-related session keys are set."""
    if "notifications" not in st.session_state:
        st.session_state["notifications"] = []
    prefs = _default_prefs()
    for key, value in prefs.items():
        st.session_state.setdefault(key, value)


def get_preference(key: str) -> Any:
    """Return a persisted user preference value."""
    initialize_notifications()
    return st.session_state.get(key, _default_prefs().get(key))


def set_preference(key: str, value: Any) -> None:
    """Persist a user preference value."""
    initialize_notifications()
    st.session_state[key] = value


def get_all_notifications() -> list[dict]:
    """Return the current notification list (newest first)."""
    initialize_notifications()
    return list(st.session_state["notifications"])


def _notification_exists(event_id: str) -> bool:
    """Check if a notification with the given event_id already exists."""
    return any(n.get("event_id") == event_id for n in st.session_state.get("notifications", []))


def add_notification(
    *,
    level: str,
    title: str,
    message: str,
    event_id: str | None = None,
    page_link: str | None = None,
) -> None:
    """Add a notification if it does not already exist.

    level: 'success', 'warning', 'critical'
    event_id: A unique, stable identifier to prevent duplicates on rerun.
    """
    initialize_notifications()
    if event_id and _notification_exists(event_id):
        return
    notification = {
        "level": level,
        "title": title,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "read": False,
        "event_id": event_id,
        "page_link": page_link,
    }
    st.session_state["notifications"].insert(0, notification)


def mark_all_read() -> None:
    """Mark all notifications as read."""
    initialize_notifications()
    for n in st.session_state["notifications"]:
        n["read"] = True


def clear_all_notifications() -> None:
    """Clear all notifications."""
    st.session_state["notifications"] = []


def unread_count() -> int:
    """Return the number of unread notifications."""
    initialize_notifications()
    return sum(1 for n in st.session_state["notifications"] if not n["read"])


def generate_system_notifications() -> None:
    """Generate real notifications based on current system state.

    Called lazily — never triggers ETL, forecasting, or analytical reruns.
    Only reads already-computed session_state values.
    """
    initialize_notifications()
    prefs = _default_prefs()

    # Upload and processing updates
    if get_preference(PREF_UPLOAD_UPDATES):
        dataset_id = st.session_state.get("active_dataset_id")
        data_status = st.session_state.get("data_status", "NO DATA")
        if dataset_id and data_status == "DATA READY":
            add_notification(
                level="success",
                title="Data processing complete",
                message="Transaction data has been successfully uploaded and processed.",
                event_id=f"etl_success_{dataset_id}",
                page_link="pages/data_upload.py",
            )
        etl_error = st.session_state.get("etl_error_message")
        if etl_error:
            error_id = f"etl_error_{hash(str(etl_error))}"
            add_notification(
                level="critical",
                title="Data processing failed",
                message=f"ETL processing encountered an error: {str(etl_error)[:120]}",
                event_id=error_id,
                page_link="pages/data_upload.py",
            )

    # Data freshness alerts
    if get_preference(PREF_DATA_FRESHNESS):
        inv_validation = st.session_state.get("inventory_validation")
        if isinstance(inv_validation, dict):
            stock_status = inv_validation.get("status", "")
            stock_age_days = inv_validation.get("age_days")
            threshold_days = get_preference(PREF_STOCK_RECENCY_DAYS)
            if stock_status in ("stale", "Stale"):
                age_str = f"{stock_age_days} days" if stock_age_days is not None else "unknown duration"
                add_notification(
                    level="warning",
                    title="Stock data is stale",
                    message=f"Current stock data is {age_str} old, exceeding the {threshold_days}-day threshold.",
                    event_id=f"stale_stock_{stock_age_days}_{threshold_days}",
                    page_link="pages/data_upload.py",
                )

    # Critical stock-out risk alerts
    if get_preference(PREF_CRITICAL_RISK):
        risk_results = st.session_state.get("risk_results")
        if risk_results is not None and not getattr(risk_results, "empty", True):
            try:
                critical_mask = risk_results.get("risk_level", risk_results.get("Risk Level", None))
                if critical_mask is None:
                    for col in risk_results.columns:
                        if "risk" in col.lower() and "level" in col.lower():
                            critical_mask = risk_results[col]
                            break
                if critical_mask is not None:
                    critical_count = int((critical_mask == "Critical").sum())
                    if critical_count > 0:
                        dataset_id = st.session_state.get("active_dataset_id", "unknown")
                        add_notification(
                            level="critical",
                            title=f"{critical_count} Critical stock-out risk SKU{'s' if critical_count != 1 else ''}",
                            message=f"{critical_count} SKU{'s are' if critical_count != 1 else ' is'} classified as Critical stock-out risk. Review replenishment recommendations.",
                            event_id=f"critical_risk_{dataset_id}_{critical_count}",
                            page_link="pages/stock_out_risk.py",
                        )
            except (AttributeError, TypeError, ValueError):
                LOGGER.exception("Critical stock-out notification generation failed.")


def format_notification_time(iso_timestamp: str) -> str:
    """Format a notification timestamp for display."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        # Make timezone-aware comparison safe
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            mins = seconds // 60
            return f"{mins}m ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        days = seconds // 86400
        return f"{days}d ago"
    except (TypeError, ValueError):
        return ""
