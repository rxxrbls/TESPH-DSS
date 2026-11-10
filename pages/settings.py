"""Tabbed Settings page for account, data guidance, and system information."""

from __future__ import annotations

import base64
import html
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from etl_config import FINAL_OUTPUT_DIR, RUNTIME_DB_PATH
from star_schema_db import DEFAULT_DB_PATH as STAR_SCHEMA_DB_PATH
from utils.account_store import (
    change_password,
    disable_two_factor,
    enable_two_factor,
    generate_totp_secret,
    get_account_profile,
    get_business_name,
    get_totp_setup_uri,
    is_two_factor_enabled,
    password_reset_email_configured,
    save_account_profile,
)
from utils.auth import get_session_timeout_minutes, set_session_timeout_minutes
from utils.components import guard_protected_page, render_page_shell, section_header
from utils.icons import icon_svg
from utils.notifications import (
    PREF_CRITICAL_RISK,
    PREF_DATA_FRESHNESS,
    PREF_UPLOAD_UPDATES,
    get_preference,
    initialize_notifications,
    set_preference,
)
from utils.state import DataStatus, get_data_status, get_inventory_data, get_inventory_validation, get_prepared_transactions


def _asset_uri(path: Path) -> str | None:
    if not path.is_file():
        return None
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _settings_styles() -> None:
    st.markdown(
        """
        <style>
        .stTabs [data-baseweb="tab-list"] { gap:1rem !important; }
        .stTabs [data-baseweb="tab-highlight"] { display:none !important; }
        [data-testid="stTabs"] [role="tab"] {
            color:#252525 !important;
            background:transparent !important;
            border:0 !important;
            border-bottom:3px solid transparent !important;
            border-radius:0 !important;
            box-shadow:none !important;
        }
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            color:#F0AD0F !important;
            background:transparent !important;
            border-bottom:3px solid #F0AD0F !important;
        }
        .settings-header { display:flex; align-items:flex-start; gap:1rem; margin:0 0 .9rem; }
        .settings-header-icon { display:grid; margin-top:1.05rem; place-items:center; width:2.4rem; height:2.4rem; flex:0 0 2.4rem; border-radius:.55rem; background:#FEF7E7; color:#D9980F; }
        .settings-header .section-title { margin:0 0 .12rem !important; font-size:1.55rem !important; font-weight:700 !important; line-height:1.25 !important; }
        .settings-header .section-description { margin-top: -.50rem !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-general-card) { gap:.65rem !important; }
        .settings-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:1rem; }
        .settings-card { padding:1rem; border:1px solid var(--tesph-border); border-radius:8px; background:#FBFCFC; box-shadow:var(--tesph-shadow); }
        .settings-card h3 { margin:.1rem 0 .65rem; font-size:1.05rem !important; }
        .settings-muted { color:var(--tesph-text-muted); font-size:.82rem; line-height:1.45; }
        .settings-general-card { margin-bottom:1rem; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-general-card) { border-radius:8px !important; box-shadow:none !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-general-card) > div { padding:.95rem 1rem !important; }
        .settings-security-card { display:none; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) > div { padding-top:0 !important; padding-bottom:1rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stVerticalBlock"] { gap:.35rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stElementContainer"]:has(.settings-card-head) { margin:0 !important; padding:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stElementContainer"]:has(.settings-separator),
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stElementContainer"]:has(div.st-key-open_two_factor_setup),
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stElementContainer"]:has(div.st-key-disable_two_factor),
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stElementContainer"]:has(div.st-key-open_change_password) { margin:0 !important; padding:0 !important; }
        .settings-card-head { display:flex; align-items:flex-start; gap:.75rem; margin-bottom:1rem; }
        .settings-card-icon { display:grid; place-items:center; width:2rem; height:2rem; flex:0 0 2rem; border-radius:.45rem; background:#FFF7E8; color:#D9980F; }
        .settings-card-title { margin:0 !important; color:#252525 !important; font-size:.95rem !important; font-weight:700 !important; line-height:1.25 !important; }
        .settings-card-copy { margin:.18rem 0 0 !important; color:#625C54 !important; font-size:.86rem !important; line-height:1.35 !important; }
        .settings-account-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:1rem; padding:.9rem 1rem; border:1px solid #F0DEC0; margin-bottom:1rem; border-radius:.45rem; background:#FFF6E6; }
        [data-testid="stElementContainer"]:has(div.st-key-settings_edit_profile) { display:flex !important; justify-content:flex-end !important; width:100% !important; }
        div.st-key-settings_edit_profile { margin-left:auto !important; width:auto !important; }
        .settings-account-label { margin:0 0 .45rem !important; color:#625C54 !important; font-size:.68rem !important; font-weight:700 !important; letter-spacing:.04em !important; text-transform:uppercase; }
        .settings-account-value { margin:0 0 .9rem !important; color:#252525 !important; font-size:.82rem !important; font-weight:650 !important; line-height:1.25 !important; }
        .settings-account-value-muted { color:#81786D !important; font-style:italic; font-weight:500 !important; }
        .settings-active-dot { display:inline-block; width:.4rem; height:.4rem; margin-right:.28rem; border-radius:999px; background:#2F7D4F; vertical-align:.08rem; }
        .settings-note { display:flex; gap:.55rem; align-items:flex-start; margin:0 0 .9rem; padding:.65rem .75rem; border:1px solid #F0DEC0; border-radius:.35rem; background:#FFF6E6; color:#85620D; font-size:.74rem; line-height:1.35; }
        .settings-notification-row { padding:.65rem 0 .7rem; border-bottom:1px solid #F0DEC0; }
        .settings-notification-row:first-of-type { border-top:1px solid #F0DEC0; }
        .settings-notification-title { margin:0 !important; color:#252525 !important; font-size:.82rem !important; font-weight:650 !important; line-height:1.25 !important; }
        .settings-notification-copy { margin:.25rem 0 0 !important; color:#625C54 !important; font-size:.72rem !important; line-height:1.35 !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) { align-items:stretch !important; gap:.75rem !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="column"] { display:flex !important; align-items:center !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="column"]:first-child { min-width:0 !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="column"]:last-child { justify-content:flex-end !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="stElementContainer"]:has([data-testid="stToggle"]) { display:flex !important; justify-content:flex-end !important; width:100% !important; margin:0 !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="stToggle"] { display:flex !important; justify-content:flex-end !important; width:100% !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="stToggle"] label { margin:0 !important; }
        .settings-field-row { display:grid; grid-template-columns:minmax(8.5rem, .6fr) minmax(0, 1fr); gap:1rem; align-items:start; margin:.3rem 0 1rem; }
        .settings-field-label { color:#252525; font-size:.82rem; font-weight:700; }
        .settings-timeout-label { display:flex; align-items:center; gap:.28rem; min-height:2.45rem; color:#252525; font-size:.82rem; font-weight:700; }
        .settings-info-icon { display:inline-grid; place-items:center; width:.72rem; height:.72rem; border:1px solid #81786D; border-radius:999px; color:#81786D; font-size:.48rem; font-weight:700; line-height:1; cursor:help; }
        [data-testid="stHorizontalBlock"]:has(.settings-timeout-label) { align-items:start !important; gap:.70rem !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-timeout-label) [data-baseweb="select"] > div { min-height:2.45rem !important; border-color:#E8E1D8 !important; background:#F7F8F9 !important; }
        .settings-field-help,
        [data-testid="stMarkdownContainer"] p.settings-field-help {
            margin:-.50rem 0 0 !important;
            color:#81786D !important;
            font-size:.80rem !important;
            line-height:1.35 !important;
        }
        .settings-separator { height:1px; margin:1rem; background:#EFE7DB; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) .settings-separator { margin:.65rem 0; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) .settings-password-separator { margin:0 !important; }
        .settings-2fa-row { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:.75rem; }
        .settings-action-row { display:grid; grid-template-columns:minmax(8.5rem, .6fr) minmax(0, 1fr); gap:1rem; align-items:center; margin-bottom:.75rem; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stElementContainer"]:has(.settings-2fa-row) { margin:0 !important; padding:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) .settings-2fa-row { min-height:3.1rem; align-items:center; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) .settings-action-row { min-height:2.45rem; align-items:center; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) [data-testid="stButton"] { margin:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) div.st-key-open_two_factor_setup,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) div.st-key-disable_two_factor,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) div.st-key-open_change_password { margin:0 !important; width:100% !important; }
        .settings-detail-row { display:grid; grid-template-columns:10rem minmax(0, 1fr); gap:.75rem; padding:.45rem 0; border-top:1px solid #EFEDEB; }
        .settings-detail-row strong { color:#625C54; font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }
        .settings-format-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:1rem; }
        .settings-format-card { display:flex; align-items:center; gap:.8rem; padding:1rem; border:1px solid var(--tesph-border); border-radius:8px; background:#FEF7E7; }
        .settings-format-card img { width:3rem; height:3rem; object-fit:contain; flex:0 0 3rem; }
        .settings-inventory-anchor { display:none; }
        [data-testid="stElementContainer"]:has(.settings-inventory-anchor) { display:none !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-inventory-anchor) { align-items:flex-start !important; gap:.70rem !important; padding-top:.25rem; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-inventory-card) { border:1px solid #D8D2C9 !important; border-radius:8px !important; background:#FFFFFF !important; box-shadow:none !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-inventory-card) > div { padding:1.5rem 1.35rem 1.35rem !important; }
        .settings-inventory-card { display:none; }
        .settings-inventory-heading { display:flex; align-items:flex-start; gap:.8rem; margin:0 0 1.25rem; }
        .settings-inventory-icon { display:grid; place-items:center; width:2rem; height:2rem; flex:0 0 2rem; border-radius:.45rem; background:#FFF7E8; color:#F09710; }
        .settings-inventory-title { margin:0 !important; color:#211F1C !important; font-size:.98rem !important; font-weight:700 !important; line-height:1.2 !important; }
        .settings-inventory-copy { margin:.25rem 0 0 !important; color:#625C54 !important; font-size:.9rem !important; line-height:1.35 !important; }
        .settings-inventory-label { margin:0 0 .75rem !important; color:#625C54 !important; font-size:.7rem !important; font-weight:700 !important; letter-spacing:.04em !important; text-transform:uppercase; }
        .settings-inventory-formats { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:1rem; margin-bottom:1rem; }
        .settings-inventory-format { display:flex; align-items:center; gap:.85rem; min-height:4.9rem; padding:.9rem 1rem; border:1px solid #E8E1D8; border-radius:7px; background:#FBFCFC; }
        .settings-inventory-format img { width:2.2rem; height:2.2rem; object-fit:contain; flex:0 0 2.2rem; }
        .settings-inventory-format strong { display:block; color:#252525; font-size:.82rem; font-weight:650; line-height:1.2; }
        .settings-inventory-format span { display:block; margin-top:.25rem; color:#625C54; font-size:.72rem; line-height:1.2; }
        .settings-inventory-note { display:flex; align-items:flex-start; gap:.65rem; margin:0 0 1rem; padding:.8rem .9rem; border:1px solid #F0DEC0; border-radius:6px; background:#FFF6E6; color:#85620D; font-size:.75rem; line-height:1.45; }
        .settings-summary-list { margin-top:.85rem; }
        .settings-summary-row { display:grid; grid-template-columns:minmax(10rem, 1fr) auto; gap:1rem; align-items:center; padding:.72rem 0; }
        .settings-summary-label { color:#625C54; font-size:.8rem; line-height:1.25; }
        .settings-summary-value { color:#252525; font-size:.78rem; font-weight:650; line-height:1.25; text-align:right; }
        .settings-status-pill { display:inline-flex; align-items:center; min-height:1.7rem; padding:.2rem .65rem; border:1px solid #E8E1D8; border-radius:5px; background:#F6F1EA; color:#6F655A; font-size:.73rem; font-weight:650; }
        div.st-key-open_data_upload { width:80rem !important; }
        div.st-key-open_data_upload button { min-height:2.45rem !important; border-color:#D8D2C9 !important; border-radius:6px !important; background:#FFFFFF !important; color:#252525 !important; font-size:.82rem !important; font-weight:650 !important; box-shadow:none !important; }
        div.st-key-open_data_upload button:hover { border-color:#D9980F !important; background:#FFF7E8 !important; }
        .settings-system-anchor { display:none; }
        [data-testid="stElementContainer"]:has(.settings-system-anchor) { display:none !important; }
        [data-testid="stHorizontalBlock"]:has(.settings-system-anchor) { align-items:flex-start !important; gap:.75rem !important; padding-top:.25rem; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-system-card) { border:1px solid #D8D2C9 !important; border-radius:8px !important; background:#FFFFFF !important; box-shadow:none !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-system-card) > div { padding:1.5rem 1.35rem 1.35rem !important; }
        .settings-system-card { display:none; }
        .settings-system-heading { display:flex; align-items:flex-start; gap:.8rem; margin:0 0 1.05rem; }
        .settings-system-icon { display:grid; place-items:center; width:2rem; height:2rem; flex:0 0 2rem; border-radius:.45rem; background:#FFF7E8; color:#F09710; }
        .settings-system-title { margin:0 !important; color:#211F1C !important; font-size:.98rem !important; font-weight:700 !important; line-height:1.2 !important; }
        .settings-system-copy { margin:.25rem 0 0 !important; color:#625C54 !important; font-size:.9rem !important; line-height:1.35 !important; }
        .settings-system-section { margin:1.1rem 0 .65rem !important; color:#625C54 !important; font-size:.7rem !important; font-weight:650 !important; letter-spacing:.04em !important; text-transform:uppercase; }
        .settings-system-section:first-of-type { margin-top:0 !important; }
        .settings-system-divider { height:1px; margin:1.45rem 0 1.25rem; background:#EFE7DB; }
        .settings-system-row { display:grid; grid-template-columns:minmax(10rem, 1fr) auto; gap:1rem; align-items:center; padding:.48rem 0; }
        .settings-system-label { color:#625C54; font-size:.8rem; line-height:1.25; }
        .settings-system-value { color:#252525; font-size:.78rem; font-weight:650; line-height:1.25; text-align:right; }
        .settings-system-connected { display:inline-flex; align-items:center; gap:.35rem; color:#2F7D4F; font-weight:650; }
        .settings-system-connected::before { content:""; width:.38rem; height:.38rem; border-radius:999px; background:#2F7D4F; }
        .settings-system-warning { display:inline-flex; align-items:center; gap:.35rem; color:#A86E08; font-weight:650; }
        .settings-system-warning::before { content:""; width:.38rem; height:.38rem; border-radius:999px; background:#A86E08; }
        @media (max-width: 760px) {
            .settings-grid, .settings-format-grid, .settings-account-grid, .settings-field-row, .settings-action-row { grid-template-columns:1fr; }
            [data-testid="stHorizontalBlock"]:has(.settings-notification-row) { gap:.25rem !important; }
            [data-testid="stHorizontalBlock"]:has(.settings-notification-row) [data-testid="column"]:last-child { justify-content:flex-start !important; padding-bottom:.45rem; }
            [data-testid="stVerticalBlockBorderWrapper"]:has(.settings-security-card) .settings-action-row { gap:.55rem; }
            [data-testid="stHorizontalBlock"]:has(.settings-inventory-anchor) { gap:1rem !important; }
            [data-testid="stHorizontalBlock"]:has(.settings-system-anchor) { gap:.65rem !important; }
            .settings-inventory-formats, .settings-summary-row, .settings-system-row { grid-template-columns:1fr; }
            .settings-summary-value, .settings-system-value { text-align:left; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _close_profile_dialog() -> None:
    st.session_state.pop("show_edit_profile_dialog", None)
    for key in ("profile_full_name",):
        st.session_state.pop(key, None)


def _close_password_dialog() -> None:
    st.session_state["show_change_password_dialog"] = False
    for key in ("settings_current_password", "settings_new_password", "settings_confirm_password"):
        st.session_state.pop(key, None)


def _close_two_factor_dialog() -> None:
    st.session_state["show_two_factor_dialog"] = False
    st.session_state.pop("pending_totp_secret", None)
    st.session_state.pop("settings_totp_code", None)


@st.dialog("Edit Profile", width="medium")
def _edit_profile_dialog(username: str) -> None:
    profile = get_account_profile(username)
    if profile is None:
        st.error("The signed-in account could not be loaded.")
        return
    st.markdown(
        """
        <style>
        [data-testid="stDialog"]:has(.edit-profile-dialog-anchor) {
            display:flex !important;
            align-items:center !important;
            justify-content:center !important;
        }
        section[role="dialog"]:has(.edit-profile-dialog-anchor) {
            margin:auto !important;
            width:min(45rem, calc(100vw - 2rem)) !important;
            max-width:calc(100vw - 2rem) !important;
        }
        section[role="dialog"]:has(.edit-profile-dialog-anchor) > h2[slot="title"] {
            padding-top:2rem !important;
            margin-bottom:-2.50rem !important;
        }
        section[role="dialog"]:has(.edit-profile-dialog-anchor) [data-testid="stElementContainer"]:has(.edit-profile-dialog-anchor) {
            display:none !important;
            height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:hidden !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<span class="edit-profile-dialog-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    st.write("Update your account information.")
    st.text_input("Full Name", value=profile.full_name, key="profile_full_name")
    st.text_input("Email Address", value=profile.email or "Not configured", disabled=True)
    st.text_input("Role", value="Administrator", disabled=True)
    cancel_col, save_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", key="cancel_profile_dialog", width="stretch"):
            _close_profile_dialog()
            st.rerun()
    with save_col:
        if st.button("Save Changes", key="save_profile_dialog", type="primary", width="stretch"):
            result = save_account_profile(
                current_username=username,
                username=profile.username,
                email=profile.email,
                business_name=get_business_name(),
                full_name=str(st.session_state["profile_full_name"]),
            )
            if result.success:
                st.session_state["authenticated_username"] = profile.username
                _close_profile_dialog()
                st.session_state["profile_update_notice"] = ("success", result.message)
                st.rerun()
            st.error(result.message)


@st.dialog("Change Password")
def _change_password_dialog(username: str) -> None:
    st.markdown(
        """
        <style>
        [data-testid="stDialog"]:has(.change-password-dialog-anchor) {
            display:flex !important;
            align-items:center !important;
            justify-content:center !important;
        }
        section[role="dialog"]:has(.change-password-dialog-anchor) {
            margin:auto !important;
            max-width:calc(100vw - 2rem) !important;
        }
        section[role="dialog"]:has(.change-password-dialog-anchor) [data-testid="stElementContainer"]:has(.change-password-dialog-anchor) {
            display:none !important;
            height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:hidden !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<span class="change-password-dialog-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    st.write("Update your password using secure credential verification.")
    current_password = st.text_input("Current Password", type="password", key="settings_current_password")
    new_password = st.text_input("New Password", type="password", key="settings_new_password")
    confirm_password = st.text_input("Confirm New Password", type="password", key="settings_confirm_password")
    st.caption("Use at least 8 characters with uppercase, lowercase, and a number.")
    cancel_col, update_col = st.columns(2)
    with cancel_col:
        st.button("Cancel", key="cancel_password_change", width="stretch", on_click=_close_password_dialog)
    with update_col:
        if st.button("Update Password", key="submit_password_change", type="primary", width="stretch"):
            if new_password != confirm_password:
                st.error("New password and confirmation do not match.")
                return
            ok, message = change_password(username, current_password, new_password)
            if ok:
                st.session_state["show_change_password_dialog"] = False
                st.session_state["password_change_notice"] = "Password updated successfully."
                st.rerun()
            st.error(message)


@st.dialog("Set Up Two-Factor Authentication")
def _two_factor_dialog(username: str) -> None:
    secret = st.session_state.setdefault("pending_totp_secret", generate_totp_secret())
    setup_uri = get_totp_setup_uri(username, str(secret), get_business_name())
    st.write("Add this account in Google Authenticator, then enter the current 6-digit code.")
    st.text_input("Manual Setup Key", value=str(secret), disabled=True)
    st.caption("In Google Authenticator, choose Add a code, then Enter a setup key.")
    st.text_area("Authenticator URI", value=setup_uri, disabled=True, height=90)
    code = st.text_input("Authentication Code", max_chars=6, key="settings_totp_code", placeholder="000000")
    cancel_col, enable_col = st.columns(2)
    with cancel_col:
        st.button("Cancel", key="cancel_two_factor_setup", width="stretch", on_click=_close_two_factor_dialog)
    with enable_col:
        if st.button("Enable 2FA", key="submit_two_factor_setup", type="primary", width="stretch"):
            ok, message = enable_two_factor(username, str(secret), code)
            if ok:
                _close_two_factor_dialog()
                st.session_state["two_factor_notice"] = ("success", message)
                st.rerun()
            st.error(message)


def _detail(label: str, value: str) -> None:
    st.markdown(
        f'<div class="settings-detail-row"><strong>{html.escape(label)}</strong><span>{html.escape(value)}</span></div>',
        unsafe_allow_html=True,
    )


def _format_pht_timestamp(value) -> str:
    timestamp = None
    if value is not None:
        try:
            timestamp = datetime.fromisoformat(str(value)).astimezone(ZoneInfo("Asia/Manila"))
        except ValueError:
            timestamp = None
    if timestamp is not None and timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ZoneInfo("Asia/Manila"))
    timestamp = timestamp or datetime.now(ZoneInfo("Asia/Manila"))
    return timestamp.strftime("%B %d, %Y %I:%M %p (PHT)")


def _latest_transaction_timestamp(transactions) -> str:
    if transactions is None or getattr(transactions, "empty", True):
        return "Not Available"
    for column in ("Time", "Order Creation Date", "Created Time", "Order Paid Time"):
        if column in getattr(transactions, "columns", []):
            parsed = pd.to_datetime(transactions[column], errors="coerce")
            if parsed.notna().any():
                return _format_pht_timestamp(parsed.max().to_pydatetime())
    return _format_pht_timestamp(None)


def _stock_as_of_value(inventory, validation: dict | None) -> str:
    candidate = (validation or {}).get("stock_as_of")
    if candidate is None and inventory is not None and not getattr(inventory, "empty", True):
        for column in ("Stock As-Of Date", "stock_as_of"):
            if column in getattr(inventory, "columns", []):
                values = pd.to_datetime(inventory[column], errors="coerce").dropna()
                if not values.empty:
                    candidate = values.max()
                    break
    if candidate is None:
        return "Not Available"
    try:
        return datetime.fromisoformat(str(candidate)).strftime("%B %d, %Y")
    except ValueError:
        return str(candidate)


def _summary_row(label: str, value: str, *, pill: bool = False) -> str:
    value_html = f'<span class="settings-status-pill">{html.escape(value)}</span>' if pill else html.escape(value)
    return (
        '<div class="settings-summary-row">'
        f'<div class="settings-summary-label">{html.escape(label)}</div>'
        f'<div class="settings-summary-value">{value_html}</div>'
        '</div>'
    )


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(__file__).resolve().parent.parent))
    except ValueError:
        return str(path)


def _sqlite_count(db_path: Path, table_name: str) -> tuple[bool, int | None]:
    if not db_path.is_file():
        return False, None
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        return True, int(count)
    except sqlite3.Error:
        return False, None


def _csv_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8-sig")) - 1
    except OSError:
        return None


def _system_row(label: str, value: str, *, status: str | None = None) -> str:
    class_name = "settings-system-value"
    if status == "connected":
        value_html = f'<span class="settings-system-connected">{html.escape(value)}</span>'
    elif status == "warning":
        value_html = f'<span class="settings-system-warning">{html.escape(value)}</span>'
    else:
        value_html = html.escape(value)
    return (
        '<div class="settings-system-row">'
        f'<div class="settings-system-label">{html.escape(label)}</div>'
        f'<div class="{class_name}">{value_html}</div>'
        '</div>'
    )


def _general_tab(profile) -> None:
    left, right = st.columns(2, gap="small")
    with left:
        with st.container(border=True):
            st.markdown('<span class="settings-general-card" aria-hidden="true"></span>', unsafe_allow_html=True)
            header_col, action_col = st.columns((1, .38), vertical_alignment="top")
            with header_col:
                st.markdown(
                    f"""
                    <div class="settings-card-head">
                      <div class="settings-card-icon">{icon_svg("user", size=17, color="#D9980F")}</div>
                      <div>
                        <p class="settings-card-title">Account Information</p>
                        <p class="settings-card-copy">View your account details and role.</p>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with action_col:
                if st.button("Edit Profile", key="settings_edit_profile"):
                    _edit_profile_dialog(profile.username)
            st.markdown(
                f"""
                <div class="settings-account-grid">
                  <div>
                    <p class="settings-account-label">Full Name</p>
                    <p class="settings-account-value">{html.escape(profile.full_name)}</p>
                    <p class="settings-account-label">Email</p>
                    <p class="settings-account-value settings-account-value-muted">{html.escape(profile.email or "Not configured")}</p>
                  </div>
                  <div>
                    <p class="settings-account-label">Role</p>
                    <p class="settings-account-value">Administrator</p>
                    <p class="settings-account-label">Account Status</p>
                    <p class="settings-account-value"><span class="settings-active-dot"></span>Active</p>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.container(border=True):
            st.markdown('<span class="settings-general-card" aria-hidden="true"></span>', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="settings-card-head">
                  <div class="settings-card-icon">{icon_svg("bell", size=17, color="#D9980F")}</div>
                  <div>
                    <p class="settings-card-title">Notifications</p>
                    <p class="settings-card-copy">Manage in-app notifications for important system updates.</p>
                  </div>
                </div>
                <div class="settings-note">
                  <span>{icon_svg("info", size=14, color="#85620D")}</span>
                  <span>Notifications are generated based on existing system results and data updates. Email or SMS notifications are not included.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            for key, label, description in (
                (
                    PREF_UPLOAD_UPDATES,
                    "Upload and Processing Updates",
                    "Notify when data upload and ETL processing is completed.",
                ),
                (
                    PREF_DATA_FRESHNESS,
                    "Data Freshness Alerts",
                    "Notify when current stock data is nearing or exceeds the 90-day threshold.",
                ),
                (
                    PREF_CRITICAL_RISK,
                    "Critical Stock-Out Risk Alerts",
                    "Notify when SKUs are classified as Critical stock-out risk.",
                ),
            ):
                text_col, toggle_col = st.columns((0.82, 0.07), vertical_alignment="center")
                with text_col:
                    st.markdown(
                        f"""
                        <div class="settings-notification-row">
                          <p class="settings-notification-title">{html.escape(label)}</p>
                          <p class="settings-notification-copy">{html.escape(description)}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with toggle_col:
                    enabled = st.toggle(
                        label,
                        value=bool(get_preference(key)),
                        key=f"settings_{key}",
                        label_visibility="collapsed",
                    )
                set_preference(key, enabled)

    with right:
        with st.container(border=True):
            st.markdown(
                f"""
                <span class="settings-general-card" aria-hidden="true"></span>
                <span class="settings-security-card" aria-hidden="true"></span>
                <div class="settings-card-head">
                  <div class="settings-card-icon">{icon_svg("shield", size=17, color="#D9980F")}</div>
                  <div>
                    <p class="settings-card-title">Security Preferences</p>
                    <p class="settings-card-copy">Manage basic security settings for your account.</p>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            label_col, timeout_col = st.columns((0.42, 0.58), vertical_alignment="top")
            with label_col:
                st.markdown(
                    '<div class="settings-timeout-label">Session Timeout '
                    '<span class="settings-info-icon" title="Choose how long your account can stay inactive before the app signs you out.">i</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            timeout_options = [15, 30, 60, 120]
            with timeout_col:
                timeout = st.selectbox(
                    "Session Timeout",
                    timeout_options,
                    index=timeout_options.index(get_session_timeout_minutes()),
                    format_func=lambda value: f"{value} minutes",
                    key="settings_session_timeout",
                    label_visibility="collapsed",
                )
                st.markdown(
                    '<p class="settings-field-help">You will be automatically logged out after the selected period of inactivity.</p>',
                    unsafe_allow_html=True,
                )
            set_session_timeout_minutes(int(timeout))
            st.markdown('<div class="settings-separator"></div>', unsafe_allow_html=True)
            two_factor_enabled = is_two_factor_enabled(profile.username)
            st.markdown(
                f"""
                <div class="settings-2fa-row">
                  <div>
                    <div class="settings-field-label">Two-Factor Authentication (2FA)</div>
                    <p class="settings-card-copy">{'Google Authenticator verification is enabled for login.' if two_factor_enabled else 'Use Google Authenticator to require a 6-digit code during login.'}</p>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if two_factor_enabled:
                if st.button("Disable 2FA", key="disable_two_factor", width="stretch"):
                    ok, message = disable_two_factor(profile.username)
                    st.session_state["two_factor_notice"] = ("success" if ok else "error", message)
                    st.rerun()
            else:
                if st.button("Set Up Google Authenticator", key="open_two_factor_setup", width="stretch"):
                    st.session_state["show_two_factor_dialog"] = True
            st.markdown('<div class="settings-separator settings-password-separator"></div>', unsafe_allow_html=True)
            st.markdown('<div class="settings-action-row"><div class="settings-field-label">Change Password</div><div>', unsafe_allow_html=True)
            if st.button("Change Password", key="open_change_password", width="stretch"):
                st.session_state["show_change_password_dialog"] = True
            st.markdown("</div></div>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown('<span class="settings-general-card" aria-hidden="true"></span>', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="settings-card-head">
                  <div class="settings-card-icon">{icon_svg("book_open", size=17, color="#D9980F")}</div>
                  <div>
                    <p class="settings-card-title">Help and Guidance</p>
                    <p class="settings-card-copy">Access the user guide and documentation.</p>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Open Help & User Guide", key="go_to_help", type="primary", width="stretch"):
                st.switch_page("pages/help_user_guide.py")


def _inventory_tab() -> None:
    status = get_data_status()
    inventory = get_inventory_data()
    validation = get_inventory_validation()
    transactions = get_prepared_transactions()
    asset_root = Path(__file__).resolve().parent.parent / "assets"
    xlsx_uri = _asset_uri(asset_root / "format_xlsx.png")
    csv_uri = _asset_uri(asset_root / "format_csv.png")
    state_label = "Data Ready" if status is DataStatus.DATA_READY else "Processing" if status is DataStatus.PROCESSING else "Not Available"
    transaction_upload = _latest_transaction_timestamp(transactions) if status is DataStatus.DATA_READY else "Not Available"
    etl_processing = _format_pht_timestamp(None) if status is DataStatus.DATA_READY else "Not Available"
    stock_upload = _format_pht_timestamp(None) if inventory is not None and not getattr(inventory, "empty", True) else "Not Available"
    stock_as_of = _stock_as_of_value(inventory, validation)

    left, right = st.columns(2, gap="large", vertical_alignment="top")
    with left:
        st.markdown('<span class="settings-inventory-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                f"""
                <span class="settings-inventory-card" aria-hidden="true"></span>
                <div class="settings-inventory-heading">
                  <div class="settings-inventory-icon">{icon_svg("upload_cloud", size=17, color="#F09710")}</div>
                  <div>
                    <p class="settings-inventory-title">Data Upload Settings</p>
                    <p class="settings-inventory-copy">Accepted formats and upload requirements.</p>
                  </div>
                </div>
                <p class="settings-inventory-label">Accepted File Formats</p>
                <div class="settings-inventory-formats">
                  <div class="settings-inventory-format">{f'<img src="{xlsx_uri}" alt="Microsoft Excel file format">' if xlsx_uri else ''}<div><strong>Microsoft Excel</strong><span>(.xlsx)</span></div></div>
                  <div class="settings-inventory-format">{f'<img src="{csv_uri}" alt="CSV file format">' if csv_uri else ''}<div><strong>CSV File</strong><span>(.csv)</span></div></div>
                </div>
                <div class="settings-inventory-note">
                  <span>{icon_svg("info", size=14, color="#D9980F")}</span>
                  <span>Make sure your file follows the required format and column headers. Refer to the Help &amp; User Guide for the template.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Go to Data Upload", key="open_data_upload"):
                st.switch_page("pages/data_upload.py")
    with right:
        with st.container(border=True):
            st.markdown(
                f"""
                <span class="settings-inventory-card" aria-hidden="true"></span>
                <div class="settings-inventory-heading">
                  <div class="settings-inventory-icon">{icon_svg("database", size=17, color="#F09710")}</div>
                  <div>
                    <p class="settings-inventory-title">Data Summary</p>
                    <p class="settings-inventory-copy">Overview of the latest uploaded and processed data.</p>
                  </div>
                </div>
                <div class="settings-summary-list">
                  {_summary_row("Last Transaction Upload", transaction_upload)}
                  {_summary_row("Last Stock Data Upload", stock_upload)}
                  {_summary_row("Last ETL Processing", etl_processing)}
                  {_summary_row("Current Stock As-Of Date", stock_as_of)}
                  {_summary_row("Data Status", state_label, pill=True)}
                </div>
                """,
                unsafe_allow_html=True,
            )


def _system_tab() -> None:
    transactions = get_prepared_transactions()
    inventory = get_inventory_data()
    validation = get_inventory_validation()
    status = get_data_status()

    operational_connected, operational_rows = _sqlite_count(RUNTIME_DB_PATH, "prepared_transactions")
    analytical_connected, analytical_rows = _sqlite_count(STAR_SCHEMA_DB_PATH, "fact_sales")
    if analytical_rows is None:
        analytical_rows = _csv_count(FINAL_OUTPUT_DIR / "fact_sales.csv")

    state_label = "Data Ready" if status is DataStatus.DATA_READY else "Processing" if status is DataStatus.PROCESSING else "Not Available"
    transaction_upload = _latest_transaction_timestamp(transactions) if status is DataStatus.DATA_READY else "Not Available"
    etl_processing = _format_pht_timestamp(None) if status is DataStatus.DATA_READY else "Not Available"
    stock_upload = _format_pht_timestamp(None) if inventory is not None and not getattr(inventory, "empty", True) else "Not Available"
    stock_as_of = _stock_as_of_value(inventory, validation)

    left, right = st.columns(2, gap="small", vertical_alignment="top")
    with left:
        st.markdown('<span class="settings-system-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                f"""
                <span class="settings-system-card" aria-hidden="true"></span>
                <div class="settings-system-heading">
                  <div class="settings-system-icon">{icon_svg("monitor", size=17, color="#F09710")}</div>
                  <div>
                    <p class="settings-system-title">System Overview</p>
                    <p class="settings-system-copy">Key information about this TheEverythingShopPH implementation.</p>
                  </div>
                </div>
                {_system_row("System Name", "TheEverythingShopPH Decision Support System (TESPH-DSS)")}
                {_system_row("Deployment Platform", "Streamlit (Local / Streamlit Community Cloud)")}
                {_system_row("Environment", "Development / Production")}
                """,
                unsafe_allow_html=True,
            )
        with st.container(border=True):
            st.markdown(
                f"""
                <span class="settings-system-card" aria-hidden="true"></span>
                <div class="settings-system-heading">
                  <div class="settings-system-icon">{icon_svg("refresh_cw", size=17, color="#F09710")}</div>
                  <div>
                    <p class="settings-system-title">Data Status</p>
                    <p class="settings-system-copy">Summary of the latest uploaded and processed data.</p>
                  </div>
                </div>
                <div class="settings-summary-list">
                  {_summary_row("Last Transaction Upload", transaction_upload)}
                  {_summary_row("Last Stock Data Upload", stock_upload)}
                  {_summary_row("Last ETL Processing", etl_processing)}
                  {_summary_row("Current Stock As-Of Date", stock_as_of)}
                  {_summary_row("Data Status", state_label, pill=True)}
                </div>
                """,
                unsafe_allow_html=True,
            )
    with right:
        with st.container(border=True):
            operational_status = "Connected" if operational_connected else "Unavailable"
            analytical_status = "Connected" if analytical_connected else "CSV Handoff Available" if analytical_rows is not None else "Unavailable"
            st.markdown(
                f"""
                <span class="settings-system-card" aria-hidden="true"></span>
                <div class="settings-system-heading">
                  <div class="settings-system-icon">{icon_svg("database", size=17, color="#F09710")}</div>
                  <div>
                    <p class="settings-system-title">Database Information</p>
                    <p class="settings-system-copy">Current database connection and status.</p>
                  </div>
                </div>
                <p class="settings-system-section">Operational Database</p>
                {_system_row("Database Engine", "SQLite Transaction Store")}
                {_system_row("Connection Status", operational_status, status="connected" if operational_connected else "warning")}
                {_system_row("Total Transaction Records", f"{operational_rows or 0:,}")}
                <div class="settings-system-divider"></div>
                <p class="settings-system-section">Analytical Database</p>
                {_system_row("Database Engine", "Star Schema Dimensional Store")}
                {_system_row("Connection Status", analytical_status, status="connected" if analytical_rows is not None else "warning")}
                {_system_row("Total Fact Sales Records", f"{analytical_rows or 0:,}")}
                """,
                unsafe_allow_html=True,
            )


guard_protected_page()
render_page_shell("Settings", "Support")
initialize_notifications()
_settings_styles()

st.markdown(
    f"""
    <div class="settings-header">
      <div class="settings-header-icon">{icon_svg("settings", size=20, color="#D9980F")}</div>
      <div>
        <h2 class="section-title">Settings</h2>
        <p class="section-description">Manage account, data guidance, and system information.</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

username = str(st.session_state.get("authenticated_username") or "")
profile = get_account_profile(username)
if profile is None:
    st.error("The signed-in account could not be loaded. Please log out and sign in again.")
    st.stop()

open_profile_from_topbar = st.session_state.pop("open_profile_from_topbar", False)
st.session_state.pop("show_edit_profile_dialog", None)
if open_profile_from_topbar:
    st.session_state["show_profile_menu"] = False
    st.session_state["show_notifications_panel"] = False
    _edit_profile_dialog(profile.username)

notice = st.session_state.pop("profile_update_notice", None)
if notice:
    kind, message = notice
    getattr(st, kind if kind in {"success", "info", "error"} else "info")(message)
password_notice = st.session_state.pop("password_change_notice", None)
if password_notice:
    st.success(password_notice)
two_factor_notice = st.session_state.pop("two_factor_notice", None)
if two_factor_notice:
    kind, message = two_factor_notice
    getattr(st, kind if kind in {"success", "info", "error"} else "info")(message)

general_tab, inventory_tab, system_tab = st.tabs(["General", "Inventory & Data", "System Information"])
with general_tab:
    _general_tab(profile)
with inventory_tab:
    _inventory_tab()
with system_tab:
    _system_tab()

if st.session_state.get("show_change_password_dialog"):
    _change_password_dialog(profile.username)
if st.session_state.get("show_two_factor_dialog"):
    _two_factor_dialog(profile.username)
