"""Local, session-based access control for the offline TESPH DSS."""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

import streamlit as st

from utils.state import reset_application_session


def _configured_credentials() -> tuple[str, str] | None:
    """Read the single local account without exposing its values to the UI."""
    try:
        auth_config = st.secrets.get("auth", {})
    except (FileNotFoundError, KeyError, OSError):
        auth_config = {}

    if isinstance(auth_config, Mapping):
        username = auth_config.get("username")
        password = auth_config.get("password")
        if isinstance(username, str) and isinstance(password, str) and username and password:
            return username, password

    # A process-local fallback supports development without a secrets file.
    username = os.getenv("TESPH_AUTH_USERNAME")
    password = os.getenv("TESPH_AUTH_PASSWORD")
    if username and password:
        return username, password
    return None


def is_authentication_configured() -> bool:
    """Return whether a local credential has been configured."""
    return _configured_credentials() is not None


def authenticate(username: str, password: str) -> bool:
    """Validate a submitted credential against the local configuration."""
    credentials = _configured_credentials()
    if credentials is None:
        return False

    configured_username, configured_password = credentials
    return hmac.compare_digest(username.encode("utf-8"), configured_username.encode("utf-8")) and hmac.compare_digest(
        password.encode("utf-8"), configured_password.encode("utf-8")
    )


def is_authenticated() -> bool:
    """Return the centralized authentication state for this browser session."""
    return bool(st.session_state.get("authenticated", False))


def start_authenticated_session() -> None:
    """Mark the current Streamlit session as authenticated after validation."""
    st.session_state["authenticated"] = True


def logout() -> None:
    """Clear temporary session data and restore the signed-out defaults."""
    reset_application_session()
