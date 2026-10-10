"""Local access control for the offline TESPH DSS."""

from __future__ import annotations

import streamlit as st
import time

from utils.account_store import authenticate_user, is_auth_configured
from utils.state import DEFAULT_STATE

DEFAULT_SESSION_TIMEOUT_MINUTES = 30
VALID_SESSION_TIMEOUT_MINUTES = (15, 30, 60, 120)


def get_session_timeout_minutes() -> int:
    """Return the configured inactivity timeout for this Streamlit session."""
    value = st.session_state.get("session_timeout_minutes")
    if value in VALID_SESSION_TIMEOUT_MINUTES:
        return int(value)
    try:
        configured = st.secrets.get("auth", {}).get("session_timeout_minutes")
    except (FileNotFoundError, KeyError, OSError):
        configured = None
    if configured in VALID_SESSION_TIMEOUT_MINUTES:
        return int(configured)
    return DEFAULT_SESSION_TIMEOUT_MINUTES


def set_session_timeout_minutes(minutes: int) -> None:
    """Persist the inactivity timeout preference in the current session."""
    if minutes in VALID_SESSION_TIMEOUT_MINUTES:
        st.session_state["session_timeout_minutes"] = int(minutes)


def is_authentication_configured() -> bool:
    """Return whether a local credential has been configured."""
    return is_auth_configured()


def authenticate(username: str, password: str) -> bool:
    """Validate a submitted credential against the operational account store."""
    return authenticate_user(username, password)


def is_authenticated() -> bool:
    """Return the centralized authentication state for this browser session."""
    if not bool(st.session_state.get("authenticated", False)):
        return False
    now = time.time()
    last_active = st.session_state.get("_last_activity_time")
    if last_active is not None and now - float(last_active) > get_session_timeout_minutes() * 60:
        logout()
        return False
    st.session_state["_last_activity_time"] = now
    return True


def start_authenticated_session(username: str | None = None) -> None:
    """Mark the current Streamlit session as authenticated after validation."""
    st.session_state["authenticated"] = True
    st.session_state["_last_activity_time"] = time.time()
    if username:
        st.session_state["authenticated_username"] = username


def logout() -> None:
    """Clear temporary session data and restore the signed-out defaults."""
    st.session_state.clear()
    st.session_state.update(DEFAULT_STATE)
