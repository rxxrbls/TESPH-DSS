"""Shared Streamlit presentation components for the TESPH DSS foundation."""

import base64
import html
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as st_components

from utils.account_store import (
    get_account_profile,
    get_business_name,
    get_logo_path,
    is_two_factor_enabled,
    request_password_reset,
    reset_password_with_token,
    verify_user_two_factor,
)
from utils.auth import (
    authenticate,
    get_session_timeout_minutes,
    is_authentication_configured,
    is_authenticated,
    logout,
    start_authenticated_session,
)
from utils.icons import icon_svg
from utils.notifications import (
    format_notification_time,
    generate_system_notifications,
    get_all_notifications,
    mark_all_read,
    unread_count,
)
from utils.state import DataStatus, get_data_status, get_etl_active_step, initialize_app_state


LOGO_PATH = "assets/theeverythingshopph-logo.png"
SIDEBAR_COLLAPSED_KEY = "tesph_sidebar_collapsed"
ETL_STEPS = (
    ("Ingest", "Receive the selected Shopee export"),
    ("Clean", "Check duplicate and missing source values"),
    ("Validate", "Check date, numeric, and financial values"),
    ("Transform", "Build canonical transactions and star schema"),
    ("Load", "Hand validated outputs to session and database"),
)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@st.cache_data(show_spinner=False)
def _logo_data_uri() -> str:
    """Embed the configured business logo in custom sidebar markup."""
    path = get_logo_path()
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    suffix = Path(path).suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{encoded}"


def refresh_branding_assets() -> None:
    """Clear cached branding assets after Settings updates."""
    _logo_data_uri.clear()


def inject_global_styles() -> None:
    """Apply the consolidated TESPH-DSS visual system across Streamlit."""
    st.markdown(
        """
        <style>
        :root {
          --tesph-canvas:#F8F6F1; --tesph-bg:#F8F6F1; --tesph-surface:#FFFFFF; --tesph-surface-muted:#FCFAF6;
          --tesph-text:#22201D; --tesph-ink:#22201D; --tesph-text-muted:#625C54; --tesph-ink-soft:#625C54;
          --tesph-text-subtle:#81786D; --tesph-ink-faint:#81786D; --tesph-border:#E4DDD2; --tesph-line:#E4DDD2;
          --tesph-border-strong:#D3C8BA; --tesph-line-strong:#D3C8BA; --tesph-brand:#D9980F; --tesph-brand-strong:#B77908;
          --tesph-brand-soft:#FFF5D6; --tesph-amber:#D9980F; --tesph-amber-hover:#B77908; --tesph-amber-tint:#FFF5D6;
          --tesph-amber-soft:#FFF3A6; --tesph-focus:rgba(217,152,15,.24); --tesph-success:#2F7D4F; --tesph-success-bg:#EAF5EE;
          --tesph-warning:#A86E08; --tesph-warning-bg:#FFF5D6; --tesph-error:#B84F3F; --tesph-error-bg:#FFF0EC;
          --tesph-info:#356F8C; --tesph-info-bg:#EEF6FA; --tesph-risk-high:#B84F3F; --tesph-risk-medium:#C99416;
          --tesph-risk-low:#3D7A53; --tesph-peach:#F8DEC5; --tesph-green:#E8F3EC; --tesph-radius:8px;
          --tesph-radius-sm:6px; --tesph-shadow:0 1px 2px rgba(32,24,12,.06), 0 8px 24px rgba(32,24,12,.04);
          --tesph-transition:120ms ease; --tesph-topbar-height:4.5rem; --tesph-topbar-control-height:2.45rem;
          --tesph-topbar-notification-width:3.15rem; --tesph-topbar-profile-width:10.75rem;
          --tesph-topbar-control-gap:.75rem; --tesph-topbar-control-inset:1.35rem;
          --tesph-upload-schema-card-height:34rem;
          --tesph-sidebar-expanded-width:18.75rem;
          --tesph-sidebar-collapsed-width:5.25rem; --tesph-sidebar-toggle-size:1.6rem;
          --tesph-sidebar-toggle-top:calc(var(--tesph-topbar-height) - 3rem);
          --tesph-sidebar-toggle-expanded-left:calc(var(--tesph-sidebar-expanded-width) - 3.5rem);
          --tesph-sidebar-toggle-collapsed-left:calc(var(--tesph-sidebar-collapsed-width) - .8rem);
          --tesph-content-gutter:clamp(1rem, 2vw, 2rem);
        }

        .stApp, [data-testid="stAppViewContainer"] { min-height:100vh; background:var(--tesph-bg) !important; color:var(--tesph-text) !important; }
        html, body, [class*="css"] { font-family:Inter, "Segoe UI", Arial, sans-serif; letter-spacing:0; }
        [data-testid="stHeader"], [data-testid="stToolbar"] { background:transparent; pointer-events:none; }
        [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"] { display:none !important; }
        .block-container { max-width:1440px !important; padding:0 var(--tesph-content-gutter) 2.5rem !important; }

        [data-testid="stMarkdownContainer"] h1 a,
        [data-testid="stMarkdownContainer"] h2 a,
        [data-testid="stMarkdownContainer"] h3 a {
         display: none !important;
        }

        section[data-testid="stSidebar"] {
            top:var(--tesph-topbar-height) !important;
            height:calc(100vh - var(--tesph-topbar-height)) !important;
            max-height:calc(100vh - var(--tesph-topbar-height)) !important;
            border-right:1px solid var(--tesph-border) !important;
            background:#FFFFFF !important;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapsedControl"] { display:none !important; }
        [data-testid="stSidebar"] [data-testid="stSidebarContent"],
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
        [data-testid="stSidebar"] > div:first-child {
            padding-top:0 !important;
            padding-bottom:.35rem !important;
            margin-top:0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            height:100% !important;
            min-height:0 !important;
            box-sizing:border-box !important;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
            flex:1 1 auto !important;
            min-height:0 !important;
            max-height:100% !important;
            box-sizing:border-box !important;
            overflow-y:auto !important;
            overscroll-behavior:contain;
        }
        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.tesph-sidebar-expanded),
        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.tesph-sidebar-collapsed) {
            display:none !important;
        }
        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded) { min-width:var(--tesph-sidebar-expanded-width) !important; width:var(--tesph-sidebar-expanded-width) !important; max-width:var(--tesph-sidebar-expanded-width) !important; display:block !important; visibility:visible !important; transform:none !important; overflow-x:hidden !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded)
[data-testid="stSidebarUserContent"] > div {
            padding-top:0 !important;
            padding-bottom:.35rem !important;
            margin-top:0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"] {
            gap:.1rem !important;
        }

/* Upload + Detected Schema equal-height cards */
[data-testid="stElementContainer"]:has(.upload-schema-row-marker) {
    display:none !important;
    height:0 !important;
    min-height:0 !important;
    margin:0 !important;
    padding:0 !important;
    overflow:hidden !important;
}
[data-testid="stHorizontalBlock"]:has(.upload-schema-row-marker)
[data-testid="stColumn"] {
    display:flex !important;
    align-items:stretch !important;
}
[data-testid="stHorizontalBlock"]:has(.upload-schema-row-marker)
[data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"]:has(.upload-schema-row-marker)
[data-testid="stColumn"] [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"]:has(.upload-schema-row-marker)
[data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stHorizontalBlock"]:has(.upload-schema-row-marker)
[data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"] > div {
    width:100% !important;
    height:100% !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.upload-card-marker),
[data-testid="stVerticalBlockBorderWrapper"]:has(.schema-card-marker) {
    min-height:var(--tesph-upload-schema-card-height) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.upload-card-marker) > div,
[data-testid="stVerticalBlockBorderWrapper"]:has(.schema-card-marker) > div {
    min-height:var(--tesph-upload-schema-card-height) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.upload-card-marker) > div {
    padding:0 1rem .75rem !important;
}
.card-header.upload-card-header {
    margin-left:-.200rem !important;
    margin-right:-.200rem !important;
    padding:.25rem 1.15rem .75rem !important;
    margin-bottom:.75rem !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.upload-card-marker) > div > [data-testid="stVerticalBlock"] {
    gap:.45rem !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.upload-card-marker) [data-testid="stElementContainer"]:has(.upload-card-marker),
[data-testid="stVerticalBlockBorderWrapper"]:has(.schema-card-marker) [data-testid="stElementContainer"]:has(.schema-card-marker) {
    display:none !important;
    height:0 !important;
    min-height:0 !important;
    margin-top:0 !important;
    padding:0 !important;
    overflow:hidden !important;
}

        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed), [data-testid="stSidebar"][aria-expanded="false"]:not(:has(.tesph-sidebar-expanded)) { min-width:var(--tesph-sidebar-collapsed-width) !important; width:var(--tesph-sidebar-collapsed-width) !important; max-width:var(--tesph-sidebar-collapsed-width) !important; display:block !important; visibility:visible !important; transform:none !important; overflow-x:hidden !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stSidebarContent"], [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stSidebarUserContent"], [data-testid="stSidebar"][aria-expanded="false"]:not(:has(.tesph-sidebar-expanded)) [data-testid="stSidebarContent"], [data-testid="stSidebar"][aria-expanded="false"]:not(:has(.tesph-sidebar-expanded)) [data-testid="stSidebarUserContent"] { min-width:var(--tesph-sidebar-collapsed-width) !important; width:var(--tesph-sidebar-collapsed-width) !important; max-width:var(--tesph-sidebar-collapsed-width) !important; padding:0 !important; overflow-x:hidden !important; }

        .tesph-topbar-spacer { height:var(--tesph-topbar-height) !important; }
        div.stElementContainer:has(.tesph-topbar), .tesph-topbar { pointer-events:none; }
        .tesph-topbar { position:fixed; inset:0 0 auto 0; z-index:100; display:grid; grid-template-columns:var(--tesph-sidebar-expanded-width) minmax(0, 1fr) auto; align-items:stretch; width:auto; height:var(--tesph-topbar-height) !important; min-height:var(--tesph-topbar-height) !important; margin:0; padding:0; overflow:hidden; background:var(--tesph-brand) !important; border-bottom:1px solid var(--tesph-brand-strong) !important; box-shadow:0 1px 0 rgba(26,18,8,.12), 0 8px 24px rgba(38,27,8,.08) !important; }
        .tesph-topbar-collapsed { grid-template-columns:var(--tesph-sidebar-collapsed-width) minmax(0, 1fr) auto !important; }

        .topbar-brand { display:flex; align-items:center; gap:.65rem; min-width:0; padding:0 4rem 0 1.15rem !important; border-right:1px solid rgba(26,18,8,.2) !important; }
        .topbar-brand img { width:2.15rem !important; height:2.15rem !important; flex:0 0 2.15rem; box-sizing:border-box; object-fit:contain; padding:.16rem; border:1px solid rgba(26,18,8,.2); border-radius:.42rem !important; background:#FFFFFF; }
        .topbar-brand-name { overflow:hidden; color:#1A1208; font-size:.88rem !important; font-weight:800 !important; line-height:1.2; text-overflow:ellipsis; white-space:nowrap; }
        .topbar-brand-subtitle { color:#4F3508 !important; font-size:.68rem !important; line-height:1.25; }
        .tesph-topbar-collapsed .topbar-brand { justify-content:center !important; padding:0 !important; gap:0 !important; }
        .tesph-topbar-collapsed .topbar-brand-name,
        .tesph-topbar-collapsed .topbar-brand-subtitle { display:none !important; }
        .topbar-page { display:flex; flex-direction:column; justify-content:center; min-width:0; padding:0 1.35rem !important; }
        .topbar-breadcrumb { margin-bottom:.18rem !important; color:#4F3508 !important; font-size:.67rem !important; font-weight:750 !important; letter-spacing:.045em !important; text-transform:uppercase; }
        .topbar-title { overflow:hidden; max-width:100%; color:#191005 !important; font-size:1.05rem !important; font-weight:800 !important; line-height:1.25 !important; text-overflow:ellipsis; white-space:nowrap; }
        .topbar-right { display:flex !important; align-items:center !important; justify-content:flex-end !important; box-sizing:border-box; height:var(--tesph-topbar-height); min-width:0; gap:var(--tesph-topbar-control-gap) !important; padding:0 var(--tesph-topbar-control-inset) 0 .7rem !important; }
        .topbar-divider { align-self:center; flex:0 0 1px; width:1px; height:1.35rem !important; background:rgba(26,18,8,.22) !important; }
        .topbar-admin { display:inline-flex; align-items:center; gap:.42rem; height:2.15rem !important; box-sizing:border-box; padding:.25rem .55rem !important; border:1px solid rgba(26,18,8,.15); border-radius:.45rem !important; background:rgba(255,255,255,.5) !important; color:#1A1208; font-size:.75rem; font-weight:750 !important; line-height:1; }
        .topbar-admin-icon { display:grid; place-items:center; width:1.1rem; height:1.1rem; border-radius:50%; background:rgba(255,255,255,.65) !important; color:#3E2C0B !important; }
        .topbar-admin-icon svg { width:.78rem; height:.78rem; fill:currentColor; }
        .topbar-admin-caret { display:inline-block !important; width:0; height:0; border-left:4px solid transparent; border-right:4px solid transparent; border-top:5px solid #3E2C0B; }
        .topbar-account-divider { height:1.25rem; margin:0 .08rem; }
        .topbar-logout-slot { width:5.25rem; height:2.25rem; flex:0 0 5.25rem; }
        div.st-key-topbar_logout { position:fixed; top:1.175rem !important; right:1.35rem !important; z-index:101; width:auto !important; }
        div.st-key-topbar_logout button { display:inline-flex !important; align-items:center !important; gap:.35rem !important; min-height:2.15rem !important; padding:.35rem .72rem !important; border:1px solid rgba(26,18,8,.18) !important; border-radius:.45rem !important; background:#FFFDF8 !important; color:#5E420B !important; font-size:.74rem !important; font-weight:750 !important; line-height:1 !important; box-shadow:none !important; }
        div.st-key-topbar_logout button::before { content:"" !important; display:none !important; }
        div.st-key-topbar_logout button:hover, div.st-key-topbar_logout button:focus { border-color:rgba(26,18,8,.32) !important; background:#FFF4C8 !important; box-shadow:0 0 0 3px rgba(255,255,255,.35) !important; }
        .topbar-control-reservation { width:calc(var(--tesph-topbar-notification-width) + var(--tesph-topbar-control-gap) + var(--tesph-topbar-profile-width)); height:var(--tesph-topbar-control-height); flex:0 0 calc(var(--tesph-topbar-notification-width) + var(--tesph-topbar-control-gap) + var(--tesph-topbar-profile-width)); }
        [data-testid="stElementContainer"]:has(div.st-key-topbar_notifications),
        [data-testid="stElementContainer"]:has(div.st-key-topbar_profile),
        [data-testid="stElementContainer"]:has(div.st-key-profile_action),
        [data-testid="stElementContainer"]:has(div.st-key-logout_action) {
            position:fixed !important;
            inset:0 auto auto 0 !important;
            z-index:101 !important;
            width:0 !important;
            height:0 !important;
            min-height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:visible !important;
        }
        div.st-key-topbar_notifications,
        div.st-key-topbar_profile { position:fixed !important; top:calc((var(--tesph-topbar-height) - var(--tesph-topbar-control-height)) / 2) !important; z-index:101; height:var(--tesph-topbar-control-height) !important; min-height:var(--tesph-topbar-control-height) !important; margin:0 !important; padding:0 !important; }
        div.st-key-topbar_notifications { top:calc((var(--tesph-topbar-height) - var(--tesph-topbar-control-height)) / 3 + 1rem) !important; }
        div.st-key-topbar_notifications { right:calc(var(--tesph-topbar-control-inset) + var(--tesph-topbar-profile-width) + var(--tesph-topbar-control-gap)) !important; width:var(--tesph-topbar-notification-width) !important; }
        div.st-key-topbar_profile { right:var(--tesph-topbar-control-inset) !important; width:var(--tesph-topbar-profile-width) !important; }
        div.st-key-topbar_notifications button { position:relative !important; display:grid !important; place-items:center !important; box-sizing:border-box !important; width:100% !important; min-width:100% !important; height:100% !important; min-height:100% !important; margin:0 !important; padding:0 !important; border:0 !important; border-radius:999px !important; background:transparent !important; color:#FFFFFF !important; box-shadow:none !important; overflow:visible !important; }
        div.st-key-topbar_notifications button::before { content:"" !important; position:absolute !important; inset:-.55rem -.25rem !important; z-index:0 !important; border-radius:999px !important; background:rgba(255,255,255,.16) !important; opacity:0 !important; transition:opacity var(--tesph-transition) !important; pointer-events:none !important; }
        div.st-key-topbar_notifications button:hover::before { opacity:1 !important; }
        div.st-key-topbar_notifications button svg { position:relative !important; z-index:1 !important; display:block !important; width:1.25rem !important; height:1.25rem !important; margin:auto !important; fill:currentColor !important; transform:none !important; }
        div.st-key-topbar_notifications button > div[data-testid="stMarkdownContainer"] { position:absolute !important; width:1px !important; height:1px !important; overflow:hidden !important; clip-path:inset(50%) !important; }
        div.st-key-topbar_notifications button:hover { background:transparent !important; box-shadow:none !important; }
        div.st-key-topbar_notifications button:focus-visible { outline:2px solid #FFFFFF !important; outline-offset:2px !important; }
        div.st-key-topbar_profile button { display:flex !important; align-items:center !important; gap:.52rem !important; width:100% !important; min-width:100% !important; height:100% !important; min-height:100% !important; box-sizing:border-box !important; margin:0 !important; padding:.28rem .65rem .28rem .34rem !important; border:1px solid rgba(255,255,255,.55) !important; border-radius:999px !important; background:#FFF7DA !important; color:#252525 !important; text-align:left !important; box-shadow:none !important; }
        div.st-key-topbar_profile button::before { display:grid; place-items:center; width:1.72rem; height:1.72rem; flex:0 0 1.72rem; border-radius:999px; background:#FFFFFF; color:#252525; font-size:.62rem; font-weight:850; line-height:1; }
        div.st-key-topbar_profile button > div[data-testid="stMarkdownContainer"] { display:flex !important; flex:1 1 auto !important; flex-direction:column !important; justify-content:center !important; min-width:0 !important; line-height:1.05 !important; }
        div.st-key-topbar_profile button p { overflow:hidden; margin:0 !important; text-overflow:ellipsis; white-space:nowrap; }
        div.st-key-topbar_profile button p:first-child { color:#252525 !important; font-size:.72rem !important; font-weight:850 !important; line-height:1.08 !important; }
        div.st-key-topbar_profile button p:last-child { color:#725A15 !important; font-size:.54rem !important; font-weight:650 !important; line-height:1.05 !important; }
        div.st-key-topbar_profile button::after { content:""; width:.44rem; height:.44rem; flex:0 0 .44rem; border-right:1.8px solid #252525; border-bottom:1.8px solid #252525; transform:rotate(45deg) translateY(-1px); }
        div.st-key-topbar_profile button:hover { background:#FFF1C2 !important; box-shadow:0 0 0 3px rgba(255,255,255,.2) !important; }
        div.st-key-topbar_profile button:focus-visible { outline:2px solid #FFFFFF !important; outline-offset:2px !important; }
        [data-testid="stElementContainer"]:has(.topbar-panel) { position:fixed !important; inset:0 auto auto 0 !important; z-index:103 !important; width:0 !important; height:0 !important; min-height:0 !important; margin:0 !important; padding:0 !important; overflow:visible !important; pointer-events:none !important; }
        [data-testid="stElementContainer"]:has(.topbar-panel) [data-testid="stMarkdownContainer"] { width:0 !important; height:0 !important; overflow:visible !important; }
        .topbar-panel { position:fixed; top:calc(var(--tesph-topbar-height) + .45rem); z-index:103; width:min(22rem, calc(100vw - 2rem)); max-height:calc(100vh - var(--tesph-topbar-height) - 1rem); overflow-y:auto; overscroll-behavior:contain; padding:.55rem; border:1px solid var(--tesph-border); border-radius:.5rem; background:#FBFCFC; box-shadow:0 18px 42px rgba(32,24,12,.18); pointer-events:auto; }
        .topbar-panel-notifications { right:calc(var(--tesph-topbar-control-inset) + var(--tesph-topbar-profile-width) + var(--tesph-topbar-control-gap)); }
        .topbar-panel-profile { right:var(--tesph-topbar-control-inset); width:min(21rem, calc(100vw - 2rem)); min-height:12.6rem; padding:1rem 1.05rem 6.25rem; border-radius:.9rem; background:#FFFFFF; box-shadow:0 14px 30px rgba(32,24,12,.14); }
        .topbar-profile-head { display:flex; align-items:center; gap:.85rem; min-width:0; padding:.15rem .1rem .85rem; border-bottom:1px solid #E8E0D5; }
        .topbar-profile-avatar { display:grid; place-items:center; width:3rem; height:3rem; flex:0 0 3rem; border-radius:999px; background:#FFF8E8; color:#D9980F; font-size:.95rem; font-weight:850; }
        .topbar-profile-name { overflow:hidden; color:#252525; font-size:1rem; font-weight:850; line-height:1.2; text-overflow:ellipsis; white-space:nowrap; }
        .topbar-profile-role { margin-top:.2rem; color:#625C54; font-size:.86rem; line-height:1.25; }
        .topbar-panel-title { margin:.25rem .35rem .5rem; font-weight:800; color:#252525; }
        .topbar-empty { margin:.25rem .35rem; color:var(--tesph-text-muted); font-size:.82rem; line-height:1.4; }
        .topbar-notification-item { padding:.65rem .7rem; border:1px solid #EFEDEB; border-radius:.45rem; background:#FFFFFF; margin:.35rem 0; }
        .topbar-notification-head { display:flex; justify-content:space-between; gap:.75rem; color:#252525; font-size:.82rem; font-weight:800; }
        .topbar-notification-copy { margin:.25rem 0 0 !important; color:var(--tesph-text-muted) !important; font-size:.75rem !important; line-height:1.35 !important; }
        .topbar-notification-time { color:#81786D; font-size:.7rem; white-space:nowrap; }
        div.st-key-profile_action button,
        div.st-key-logout_action button { justify-content:center !important; min-height:2.50rem !important; padding:.45rem .65rem !important; border:1px solid #F6F1E8 !important; border-radius:.6rem !important; background:#FFFFFF !important; color:#3D3832 !important; text-align:center !important; font-size:.92rem !important; font-weight:500 !important; box-shadow:0 6px 16px rgba(32,24,12,.025) !important; }
        div.st-key-profile_action button:hover,
        div.st-key-logout_action button:hover { background:#FEF7E7 !important; border-color:#F1D28B !important; }
        div.st-key-profile_action,
        div.st-key-logout_action { position:fixed !important; right:calc(var(--tesph-topbar-control-inset) + 1.05rem) !important; z-index:104 !important; width:min(18.9rem, calc(100vw - 4.1rem)) !important; margin:0 !important; padding:0 !important; }
        div.st-key-profile_action { top:calc(var(--tesph-topbar-height) + 6.5rem) !important; }
        div.st-key-logout_action { top:calc(var(--tesph-topbar-height) + 9.5rem) !important; }

        div.st-key-tesph_sidebar_toggle_expanded, div.st-key-tesph_sidebar_toggle_collapsed { width:var(--tesph-sidebar-toggle-size) !important; min-width:var(--tesph-sidebar-toggle-size) !important; }
        div.st-key-tesph_sidebar_toggle_expanded { position:fixed !important; top:var(--tesph-sidebar-toggle-top) !important; left:var(--tesph-sidebar-toggle-expanded-left) !important; z-index:102 !important; margin:0 !important; }
        div.st-key-tesph_sidebar_toggle_collapsed { position:fixed !important; top:var(--tesph-sidebar-toggle-top) !important; left:var(--tesph-sidebar-toggle-collapsed-left) !important; z-index:102 !important; width:var(--tesph-sidebar-toggle-size) !important; min-width:var(--tesph-sidebar-toggle-size) !important; margin:0 !important; }
        div.st-key-tesph_sidebar_toggle_expanded button, div.st-key-tesph_sidebar_toggle_collapsed button { display:grid !important; place-items:center !important; width:var(--tesph-sidebar-toggle-size) !important; min-width:var(--tesph-sidebar-toggle-size) !important; height:var(--tesph-sidebar-toggle-size) !important; min-height:var(--tesph-sidebar-toggle-size) !important; padding:0 !important; border:#c78616 !important; border-radius:.42rem !important; background:rgba(255, 212, 138, 0.35) !important; color:#FFFFFF !important; font-size:.8rem !important; font-weight:800 !important; line-height:1 !important; box-shadow:none !important; }
        div.st-key-tesph_sidebar_toggle_collapsed button { border-color: #c78616 !important; background: rgba(255, 212, 138, 0.35) !important; color: #FFFFFF !important; }
        div.st-key-tesph_sidebar_toggle_expanded button:hover, div.st-key-tesph_sidebar_toggle_collapsed button:hover { border-color:#a36e14 !important; background:rgba(280, 240, 138, 0.35) !important; }
        div.st-key-tesph_sidebar_toggle_collapsed button:hover { border-color:#a36e14 !important; background: rgba(280, 240, 138, 0.35) !important; }

        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded) .nav-section {
            margin:.22rem .5rem .18rem !important;
            margin-bottom:.35rem !important;
            color:#625C54 !important;
            font-size:.70rem !important;
            font-weight:900 !important;
            line-height:1.25 !important;
            text-transform:uppercase;
            letter-spacing:.075em !important;
        }
        .nav-gate-note { margin:.45rem .75rem !important; padding:.55rem .65rem !important; border:1px solid var(--tesph-border) !important; border-left:3px solid var(--tesph-info) !important; border-radius:.45rem !important; background:var(--tesph-info-bg) !important; color:#305D72 !important; font-size:.73rem !important; line-height:1.4 !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded) [data-testid="stPageLink-NavLink"] { display:flex !important; align-items:center !important; box-sizing:border-box !important; width: calc(100% - 0rem) !important;
        max-width: calc(100% - 0.20rem) !important;
        min-height:2.25rem !important;
        margin: .13rem .1rem !important;
        padding: .20rem .7rem !important;border:1px solid transparent !important; border-radius:.45rem !important; color:var(--tesph-text-muted) !important; font-size:.96rem !important; font-weight:500 !important; line-height:2 !important; opacity:1 !important; transition:background var(--tesph-transition), border-color var(--tesph-transition), color var(--tesph-transition), transform var(--tesph-transition); }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] * { color:inherit !important; opacity:1 !important; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] svg { stroke:currentColor !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded) [data-testid="stPageLink-NavLink"]:hover { border-color:#E8D6A6 !important; background:#FFF8E2 !important; color:var(--tesph-text) !important; transform:translateX(1px); }
        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded) [aria-current="page"] { border-color:#E4C164 !important; background:#FFF4C8 !important; color:var(--tesph-text) !important; font-weight:750 !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-expanded) [aria-current="page"]::before { content:""; position:absolute; left:0; top:50%; transform:translateY(-50%); width:3px !important; height:1.45rem !important; border-radius:0 4px 4px 0; background:var(--tesph-brand-strong) !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) .nav-section, [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) .nav-gate-note { display:none !important; }
        .tesph-rail-group-start { display:none; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) .tesph-rail-group-start { display:block; height:.18rem; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] { justify-content:center !important; width:2.75rem !important; min-width:2.75rem !important; height:2.75rem !important; min-height:2.75rem !important; margin:.16rem auto !important; padding:0 !important; border-radius:.6rem !important; overflow:hidden !important; color:#625C54 !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] * { margin:0 !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] svg { width:1.25rem !important; height:1.25rem !important; flex:0 0 1.25rem !important; color:inherit !important; fill:currentColor !important; stroke:currentColor !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] span { color:inherit !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] span:not(:first-child), [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] p, [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] div:not(:first-child), [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [data-testid="stPageLink-NavLink"] [data-testid="stMarkdownContainer"] { position:absolute !important; width:1px !important; height:1px !important; overflow:hidden !important; clip:rect(0 0 0 0) !important; white-space:nowrap !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [aria-current="page"] { border-color:#E4C164 !important; background:#FFF4C8 !important; color:#3D3832 !important; box-shadow:inset 0 0 0 1px rgba(183,121,8,.18) !important; }
        [data-testid="stSidebar"]:has(.tesph-sidebar-collapsed) [aria-current="page"]::before { display:none !important; }

        h1, h2, h3, h4, h5, h6, .section-title, .card-title, .empty-title, .state-title { color:var(--tesph-text) !important; letter-spacing:0 !important; }
        [data-testid="stCaptionContainer"], .section-description, .card-subtitle, .empty-copy, .state-copy, .file-meta, .schema-copy, .upload-zone-copy { color:var(--tesph-text-muted) !important; }
        .section-title { margin:1.65rem 0 .12rem !important; color:#1F1F1F !important; font-size:1.55rem !important; line-height:.25 !important; font-weight:700 !important; }
        .section-description { max-width:72rem; margin:0 0 .7rem !important; color:#6B6259 !important; font-size:.82rem !important; line-height:1.45 !important; }
        [data-testid="stVerticalBlockBorderWrapper"] { border:1px solid var(--tesph-border) !important; border-radius:var(--tesph-radius) !important; background:var(--tesph-surface) !important; box-shadow:var(--tesph-shadow); }
        .card-header { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding:1rem 1.15rem !important; border-bottom:1px solid var(--tesph-border) !important; }
        .card-title {
            margin:0;
            color:#1F1F1F !important;
            font-size:1.55rem !important;
            font-weight:700 !important;
            line-height:.25 !important;
        }
        .card-subtitle { margin:.16rem 0 0; color:var(--tesph-text-muted) !important; font-size:.75rem; }
        .category-mix-card { overflow:hidden; border:1px solid #E4DDD2 !important; border-radius:0 !important; background:#FFFFFF !important; box-shadow:none !important; }
        .category-mix-body { display:grid; grid-template-columns:minmax(7.5rem, .85fr) minmax(10rem, 1fr); align-items:center; gap:1.05rem; min-height:360px; padding:1.15rem 1rem !important; }
        .category-mix-donut { width:min(11.5rem, 100%); aspect-ratio:1; border-radius:50%; position:relative; justify-self:center; box-shadow:inset 0 0 0 1px rgba(32,24,12,.04); }
        .category-mix-donut::after { content:""; position:absolute; inset:24%; border-radius:50%; background:var(--tesph-surface); box-shadow:0 0 0 1px rgba(32,24,12,.03); }
        .category-mix-legend { display:flex; flex-direction:column; gap:.62rem; min-width:0; }
        .category-mix-row { display:grid; grid-template-columns:.65rem minmax(0, 1fr) auto; align-items:start; gap:.55rem; color:var(--tesph-text-muted) !important; font-size:.84rem !important; line-height:1.25 !important; }
        .category-mix-dot { width:.58rem; height:.58rem; margin-top:.23rem; border-radius:.2rem; }
        .category-mix-name { min-width:0; overflow-wrap:anywhere; }
        .category-mix-share { color:var(--tesph-text) !important; font-family:"SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size:.82rem !important; font-weight:700 !important; white-space:nowrap; }
        .priority-list { display:flex; flex-direction:column; overflow:hidden; box-sizing:border-box; border:0px solid var(--tesph-border) !important; border-radius:0 !important; background:var(--tesph-surface) !important; box-shadow:none !important; }
        .priority-row { display:flex; flex:1 1 0; align-items:center; justify-content:space-between; gap:1rem; min-height:0; padding:.82rem 1.05rem !important; border-bottom:1px solid var(--tesph-border) !important; }
        .priority-item { min-width:0; }
        .priority-product { overflow:hidden; color:var(--tesph-text) !important; font-size:.9rem !important; font-weight:400 !important; line-height:1.22 !important; text-overflow:ellipsis; white-space:nowrap; }
        .priority-units { margin-top:.14rem; color:var(--tesph-text-subtle) !important; font-size:.78rem !important; font-family:"SFMono-Regular", Consolas, "Liberation Mono", monospace; line-height:1.2 !important; }
        .priority-badge { flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center; max-width:8rem; min-height:1.5rem; padding:.22rem .52rem !important; border:1px solid #E9C9AA !important; border-radius:.45rem !important; background:#F7DEC5 !important; color:#805127 !important; font-size:.7rem !important; font-weight:750 !important; line-height:1 !important; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .priority-note { margin:0 !important; padding:.9rem 1.05rem 1rem !important; color:var(--tesph-text-subtle) !important; font-size:.78rem !important; line-height:1.35 !important; }
        .kpi-card { min-height:6.45rem !important; padding:1rem 1.05rem !important; border:1px solid var(--tesph-border) !important; border-radius:var(--tesph-radius) !important; background:var(--tesph-surface) !important; box-shadow:var(--tesph-shadow); }
        .kpi-label { color:var(--tesph-text-subtle) !important; font-size:.68rem !important; font-weight:700 !important; letter-spacing:.04em !important; text-transform:uppercase; }
        .kpi-skeleton { width:4.8rem; height:1.55rem; margin-top:.75rem; border-radius:.25rem; background:#EEE8DE !important; }
        .kpi-value { margin-top:.45rem; color:var(--tesph-text) !important; font-size:clamp(1.25rem, 1.8vw, 1.58rem) !important; font-weight:700; line-height:1.18 !important; }
        .empty-panel { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:16rem !important; padding:3rem 1.5rem; border:1px dashed var(--tesph-border-strong) !important; border-radius:var(--tesph-radius) !important; background:var(--tesph-surface) !important; text-align:center; }
        .empty-icon { display:grid; place-items:center; width:3rem; height:3rem; border-radius:var(--tesph-radius) !important; background:var(--tesph-brand-soft) !important; color:var(--tesph-warning) !important; font-size:1.25rem; }
        .empty-title { margin:1rem 0 .4rem; color:var(--tesph-text) !important; font-size:1.05rem; font-weight:700; }
        .empty-copy { max-width:25rem; margin:0; color:var(--tesph-text-muted) !important; font-size:.85rem; line-height:1.5; }
        .status-badge { display:inline-flex; align-items:center; gap:.3rem; border:1px solid var(--tesph-border); border-radius:var(--tesph-radius-sm) !important; padding:.22rem .48rem; font-size:.72rem; font-weight:700 !important; }
        .badge-high { background:var(--tesph-error-bg) !important; color:var(--tesph-risk-high) !important; border-color:#E3B3AA !important; }
        .badge-medium { background:var(--tesph-warning-bg) !important; color:var(--tesph-risk-medium) !important; border-color:#E2BD58 !important; }
        .badge-low { background:var(--tesph-success-bg) !important; color:var(--tesph-risk-low) !important; border-color:#BFDCC9 !important; }
        .badge-neutral { background:var(--tesph-info-bg) !important; color:var(--tesph-info) !important; border-color:#C4DCE8 !important; }

        .data-status { display:inline-flex; align-self:center; align-items:center; box-sizing:border-box; gap:.43rem; height:2.15rem !important; padding:0 .7rem !important; border:1px solid rgba(26,18,8,.18) !important; border-radius:var(--tesph-radius-sm); background:rgba(255,255,255,.56) !important; color:#1A1208 !important; font-size:.74rem !important; font-weight:750 !important; white-space:nowrap; }
        .data-dot { width:.5rem !important; height:.5rem !important; border-radius:50%; }
        .status-empty .data-dot { background:#C8C4BC; }
        .status-processing .data-dot { background:#D4904A; animation:tesph-pulse 1.2s infinite; }
        .status-ready .data-dot { background:var(--tesph-success); }
        @keyframes tesph-pulse { 0%,100% { opacity:1; } 50% { opacity:.35; } }

        .stButton > button, [data-testid="stFormSubmitButton"] > button, [data-testid="stFileUploaderDropzone"] button { min-height:2.45rem; border-radius:var(--tesph-radius-sm) !important; font-size:.84rem; font-weight:600; transition:background var(--tesph-transition), border-color var(--tesph-transition), box-shadow var(--tesph-transition); }
        .stButton > button:focus, [data-testid="stFormSubmitButton"] > button:focus, [data-testid="stTextInput"] [data-baseweb="input"]:focus-within, [data-testid="stNumberInput"] [data-baseweb="input"]:focus-within, [data-testid="stDateInput"] [data-baseweb="input"]:focus-within, [data-testid="stFileUploaderDropzone"] button:focus { box-shadow:0 0 0 3px var(--tesph-focus) !important; }
        [data-testid="stFormSubmitButton"] > button, .stButton > button[kind="primary"] { border-color:var(--tesph-brand) !important; background:var(--tesph-brand) !important; color:#1A1208 !important; }
        [data-testid="stFormSubmitButton"] > button:hover, .stButton > button[kind="primary"]:hover { border-color:var(--tesph-brand-strong) !important; background:var(--tesph-brand-strong) !important; color:#FFFFFF !important; }
        .stButton > button[kind="secondary"], [data-testid="stFileUploaderDropzone"] button { border-color:var(--tesph-border-strong) !important; background:var(--tesph-surface) !important; color:var(--tesph-text) !important; }
        .stButton > button[kind="secondary"]:hover, [data-testid="stFileUploaderDropzone"] button:hover { border-color:var(--tesph-brand) !important; background:var(--tesph-brand-soft) !important; }
        .stButton > button:disabled { background:#EEE9DF !important; border-color:var(--tesph-border) !important; color:var(--tesph-text-subtle) !important; opacity:1 !important; }
        [data-testid="stTextInput"] label, [data-testid="stTextInput"] label span, [data-testid="stNumberInput"] label, [data-testid="stDateInput"] label, [data-testid="stCheckbox"] label { color:var(--tesph-text-muted) !important; font-size:.76rem !important; font-weight:700 !important; }
        [data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stNumberInput"] [data-baseweb="input"], [data-testid="stDateInput"] [data-baseweb="input"] { min-height:2.625rem; border:1px solid var(--tesph-border-strong) !important; border-radius:var(--tesph-radius-sm) !important; background:var(--tesph-surface) !important; box-shadow:none !important; }
        [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stDateInput"] input { background:#FFFFFF !important; color:var(--tesph-text) !important; -webkit-text-fill-color:var(--tesph-text) !important; }
        [data-testid="stTextInput"] input::placeholder { color:#827A70 !important; opacity:1 !important; -webkit-text-fill-color:#827A70 !important; }
        [data-testid="stTextInput"] button { color:var(--tesph-text-muted) !important; }
        [data-testid="stTextInput"] button:hover { color:var(--tesph-text) !important; background:var(--tesph-brand-soft) !important; }
        [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] { background:#FFFFFF !important; }

        .block-container:has(.login-spacer) { padding-top:0 !important; padding-bottom:.5rem !important; }
        .login-spacer { height:clamp(.15rem, 1vh, .5rem) !important; }
        .login-brand { display:flex; flex-direction:column; align-items:center; text-align:center; margin-bottom:clamp(.55rem, 1.5vh, 1rem) !important; }
        .login-brand img { width:min(9rem, 17vh) !important; height:min(9rem, 17vh) !important; object-fit:contain; padding:.42rem; border:1px solid var(--tesph-border) !important; border-radius:.75rem !important; background:#FFFFFF; box-shadow:0 10px 28px rgba(55,43,22,.08); }
        .login-title { margin:clamp(.35rem, 1vh, .65rem) 0 .15rem !important; color:var(--tesph-text) !important; font-size:clamp(1.45rem, 4vh, 2rem) !important; font-weight:750 !important; line-height:1.12 !important; }
        .login-subtitle { max-width:22rem; margin:0 auto !important; color:var(--tesph-text-muted) !important; font-size:clamp(.8rem, 2vh, .92rem) !important; line-height:1.3 !important; }
        .login-form-heading, .login-form-note { display:none; }
        .login-forgot-wrap { position:relative; top:-.35rem; display:flex; height:2rem; min-height:2rem; align-items:center; justify-content:flex-end; }
        .login-forgot-link { display:inline-flex; align-items:center; height:2rem; color:#D9980F !important; font-size:.82rem; font-weight:700; line-height:1; text-decoration:none !important; cursor:pointer; white-space:nowrap; }
        .login-forgot-link:hover, .login-forgot-link:focus { color:#B77908 !important; text-decoration:underline !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) { border:1px solid var(--tesph-border) !important; border-radius:.75rem !important; box-shadow:0 14px 40px rgba(42,31,12,.08) !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) > div { padding:clamp(.85rem, 2.2vh, 1.5rem) !important; }
        [data-testid="stElementContainer"]:has(.two-factor-verification-anchor) { display:none !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.two-factor-verification-anchor) > div { padding-top:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.two-factor-verification-anchor) [data-testid="stVerticalBlock"] { gap:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stForm"] { border:0 !important; padding:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor):has(h3):has([data-testid="stTextInput"]) h3,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor):has(h3):has([data-testid="stTextInput"]) [data-testid="stCaptionContainer"] { text-align:center !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.two-factor-verification-anchor) h1,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.two-factor-verification-anchor) h2,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.two-factor-verification-anchor) h3 { margin-top:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] { align-items:center !important; min-height:2rem !important; margin-top:-.2rem !important; margin-bottom:.85rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] [data-testid="stColumn"] { display:flex !important; align-items:center !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child { justify-content:flex-end !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] [data-testid="stElementContainer"]:has([data-testid="stCheckbox"]) { margin:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] { height:2rem !important; min-height:1rem !important; display:flex !important; align-items:center !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] label { display:flex !important; align-items:center !important; height:2rem !important; min-height:2rem !important; padding:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stElementContainer"]:has(.login-options-anchor) + [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] label p { margin:0 !important; line-height:1 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] { margin-bottom:clamp(.3rem, 1vh, .65rem) !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] label,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] label span { font-size:.78rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] [data-baseweb="input"] { min-height:clamp(2.35rem, 5vh, 2.8rem) !important; border-radius:.45rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] button,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] button:hover,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] button:focus { background:#FFFFFF !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stFormSubmitButton"] > button { min-height:clamp(2.35rem, 5vh, 2.8rem) !important; margin-top:.1rem !important; border-radius:.45rem !important; font-size:.94rem !important; font-weight:750 !important; }
        .login-note { max-width:26rem !important; margin:clamp(.5rem, 1.4vh, .9rem) auto 0 !important; color:var(--tesph-text-subtle) !important; font-size:.76rem !important; line-height:1.35 !important; text-align:center; }
        @media (max-height:640px) {
            .login-brand { margin-bottom:.4rem !important; }
            .login-brand img { width:min(6rem, 14vh) !important; height:min(6rem, 14vh) !important; }
            .login-title { margin:.25rem 0 .1rem !important; font-size:clamp(1.3rem, 3.5vh, 1.65rem) !important; }
            [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) > div { padding:.65rem !important; }
            [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] { margin-bottom:.2rem !important; }
            [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-baseweb="input"] { min-height:2.1rem !important; }
            [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stFormSubmitButton"] > button { min-height:2.1rem !important; }
            .login-note { margin:.35rem auto 0 !important; line-height:1.2 !important; }
        }

        [data-testid="stElementContainer"]:has(.validation-cards-start)
        + [data-testid="stHorizontalBlock"] {
            margin-left:1rem !important;
            margin-right:1rem !important;
            width:calc(100% - 2rem) !important;
        }

    .validation-card-header {
    display:flex !important;
    align-items:center !important;
    justify-content:space-between !important;
    gap:.5rem !important;
    margin-bottom:.75rem !important;
}

.validation-checks-title {
    margin:1.25rem 1rem 1rem !important;
    color:var(--tesph-text) !important;
    font-size:1.55rem !important;
    font-weight:700 !important;
    line-height:1.25 !important;
}

.validation-card {
    height:130px !important;
    box-sizing:border-box !important;
    padding:1rem !important;
    margin-bottom:1rem !important;

    background:#FFFFFF !important;
    border:1px solid var(--tesph-border) !important;
    border-radius:.5rem !important;

    overflow:hidden !important;
}

.validation-card-title {
    margin:0 !important;
    color:var(--tesph-text) !important;
    font-size:.88rem !important;
    font-weight:700 !important;
}

.validation-card-status {
    margin:0 !important;
    color:var(--tesph-text-subtle) !important;
    font-size:.72rem !important;
    font-weight:500 !important;
    line-height:1.3 !important;
}

.validation-card-info {
    margin:0 !important;
    color:var(--tesph-text-muted) !important;
    font-size:.72rem !important;
    line-height:1.35 !important;
}

        .upload-zone { text-align: center !important; border:1px dashed rgba(137, 103, 37, .42); border-radius:.75rem; background:#FFFDF8; padding:1.25rem; margin-bottom:.75rem; }
        .upload-zone-title { margin-top:.85rem !important; }
        [data-testid="stFileUploader"] { border:1px dashed rgba(137, 103, 37, .38) !important; border-radius:.75rem !important; padding:.85rem !important; background:#FFFDF8 !important; }
        [data-testid="stFileUploader"] section { border:0 !important; padding:.5rem !important; }
        [data-testid="stFileUploader"] small { color:var(--tesph-text-subtle) !important; }
        [data-testid="stFileUploader"] {
            margin-top: 0 !important;
        }

        [data-testid="stFileUploaderDropzone"] {
            min-height: 72px !important;
            padding: .75rem 1rem !important;

            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }

        [data-testid="stFileUploaderDropzoneInstructions"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        [data-testid="stFileUploaderDropzone"] > div {
            width: auto !important;
            flex: 0 1 auto !important;
        }

        [data-testid="stFileUploaderDropzone"] button {
            margin: 0 !important;
        }

        .etl-grid { display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:.7rem; padding:1.15rem; }
        .etl-step { min-height:8.1rem; padding:.85rem; border:1px solid var(--tesph-border); border-radius:.5rem; background:var(--tesph-bg); }
        .etl-step-active { border-color:#E8D8A0; background:var(--tesph-brand-soft); }
        .etl-step-done { border-color:#C8E0D0; background:#EDF7F0; }
        .etl-number { display:grid; place-items:center; width:1.45rem; height:1.45rem; border-radius:50%; background:var(--tesph-border-strong); color:#FFFFFF; font-size:.67rem; font-weight:700; }
        .etl-step-active .etl-number { background:var(--tesph-brand); color:#22201D; }
        .etl-step-done .etl-number { background:var(--tesph-success); }
        .etl-name { margin-top:.72rem; color:var(--tesph-text); font-size:.78rem; font-weight:700; }
        .etl-copy { margin:.3rem 0 0; color:var(--tesph-text-subtle); font-size:.67rem; line-height:1.35; }
        .etl-ready { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin:0 1.15rem 1.15rem; padding:.85rem 1rem; border:1px solid #C8E0D0; border-radius:.5rem; background:#EDF7F0; }
        .etl-ready-title { color:var(--tesph-success); font-size:.82rem; font-weight:700; }
        .etl-ready-copy { margin-top:.12rem; color:var(--tesph-text-muted); font-size:.72rem; }
        .processing-panel, .success-panel, .validation-panel { margin:.9rem 0; padding:1rem 1.1rem; border-radius:.5rem; }
        .processing-panel { border:1px solid #E8D9A8; background:#FFFAE8; }
        .success-panel { border:1px solid #C8E0D0; background:#EDF7F0; }
        .validation-panel { border:1px solid #E9C8BF; background:#FFF6F3; }
        .state-title { margin:0 0 .24rem; color:var(--tesph-text); font-size:.93rem; font-weight:700; }
        .state-copy { margin:0; color:var(--tesph-text-muted); font-size:.8rem; line-height:1.45; }
        .validation-list { margin:.7rem 0 0 1.15rem; padding:0; color:var(--tesph-text-muted); font-size:.8rem; line-height:1.55; }
        .success-metric { margin-top:.7rem; color:var(--tesph-success); font-size:.78rem; font-weight:600; }

        .status-message, .empty-state, .validation-state, .loading-state { border-radius:.75rem !important; border:1px solid var(--tesph-border); padding:1rem 1.1rem; background:#FFFFFF; }
        .empty-state { display:flex; flex-direction:column; gap:.35rem; align-items:flex-start; }
        .empty-state h3 { margin:0 !important; color:var(--tesph-text) !important; font-size:1rem !important; }
        .empty-state p { margin:0 !important; color:var(--tesph-text-muted) !important; font-size:.86rem !important; }
        .validation-state { border-color:rgba(178, 92, 0, .32); background:#FFF7EA; color:var(--tesph-warning); }
        .loading-state { border-color:rgba(52, 97, 167, .24); background:#F4F8FF; color:var(--tesph-info); }
        [data-testid="stAlert"] { border-radius:.65rem !important; border:1px solid var(--tesph-border) !important; box-shadow:none !important; }
        [data-testid="stAlert"] div { font-size:.86rem !important; line-height:1.45 !important; }

        [data-testid="stDataFrame"] { border:1px solid var(--tesph-border) !important; border-radius:.65rem !important; overflow:hidden !important; }
        [data-testid="stTable"] { border:1px solid var(--tesph-border) !important; border-radius:.65rem !important; overflow:hidden !important; }
        [data-testid="stMetric"] { background:#FFFFFF !important; border:1px solid var(--tesph-border) !important; border-radius:.65rem !important; padding:.85rem !important; }
        [data-testid="stMetricLabel"] { color:var(--tesph-text-muted) !important; font-size:.75rem !important; font-weight:700 !important; text-transform:uppercase !important; letter-spacing:.04em !important; }
        [data-testid="stMetricValue"] { color:var(--tesph-text) !important; font-size:1.55rem !important; font-weight:760 !important; }

        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        .block-container {
            overflow-x:clip !important;
            box-sizing:border-box !important;
        }

        [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"],
        [data-testid="column"],
        [data-testid="stElementContainer"] {
            min-width:0 !important;
            box-sizing:border-box !important;
        }

        [data-testid="stMarkdownContainer"],
        [data-testid="stCaptionContainer"],
        .card-title,
        .card-subtitle,
        .section-title,
        .section-description,
        .priority-product,
        .category-mix-name,
        .schema-copy,
        .upload-summary-name,
        .validation-card-title,
        .validation-card-status,
        .validation-card-info {
            overflow-wrap:anywhere;
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"],
        [data-testid="stDataFrameResizable"],
        [data-testid="stDataFrameGlideDataEditor"] {
            max-width:100% !important;
            overflow-x:auto !important;
        }

        [data-testid="stTable"] table {
            width:max-content !important;
            min-width:100% !important;
        }

        [data-testid="stPlotlyChart"],
        [data-testid="stVegaLiteChart"],
        [data-testid="stAltairChart"],
        [data-testid="stDeckGlJsonChart"] {
            max-width:100% !important;
            overflow:hidden !important;
        }


        @media (max-width:1100px) {
            :root {
                --tesph-topbar-profile-width:9.75rem;
                --tesph-topbar-control-gap:.55rem;
                --tesph-topbar-control-inset:1rem;
            }
            .block-container { padding-left:1.25rem !important; padding-right:1.25rem !important; }
            .topbar-brand { padding:0 3rem 0 1rem !important; }
            .topbar-page { padding:0 1rem !important; }
            .topbar-right { padding:0 var(--tesph-topbar-control-inset) 0 .55rem !important; }
            .topbar-title { font-size:1rem !important; }
            .topbar-breadcrumb { font-size:.65rem !important; }
            .data-status, .topbar-admin { padding:0 .55rem !important; }
            .data-status span { max-width:8.5rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            div.st-key-topbar_profile button { gap:.42rem !important; padding:.24rem .55rem .24rem .3rem !important; }
            .etl-grid { grid-template-columns:repeat(3, minmax(0, 1fr)); }
        }

        @media (max-width:960px) {
            :root {
                --tesph-topbar-profile-width:8.75rem;
                --tesph-topbar-notification-width:2.85rem;
                --tesph-topbar-control-gap:.45rem;
                --tesph-topbar-control-inset:.85rem;
                --tesph-sidebar-toggle-expanded-left:calc(var(--tesph-sidebar-collapsed-width) - .85rem);
            }
            .tesph-topbar { grid-template-columns:var(--tesph-sidebar-collapsed-width) minmax(0, 1fr) auto !important; }
            .topbar-brand { justify-content:center !important; padding:0 !important; gap:0 !important; }
            .topbar-brand-name,
            .topbar-brand-subtitle { display:none !important; }
            .topbar-page { padding:0 .85rem !important; }
            .topbar-title { font-size:.96rem !important; }
            .data-status span { max-width:5.5rem; }
            div.st-key-topbar_profile button p:first-child { font-size:.68rem !important; }
        }

        @media (max-width:860px) {
            .block-container { padding-left:1rem !important; padding-right:1rem !important; }
            .tesph-topbar { grid-template-columns:minmax(0, 1fr) auto !important; }
            .topbar-brand { display:none !important; }
            .topbar-admin span, .data-status span { max-width:7rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .etl-grid { grid-template-columns:1fr; }
            .etl-step { min-height:auto; }
            .category-mix-body { grid-template-columns:1fr; min-height:auto; }
            .priority-row { align-items:flex-start; flex-wrap:wrap; }
        }

        @media (max-width:620px) {
            :root {
                --tesph-topbar-profile-width:6.35rem;
                --tesph-topbar-notification-width:2.55rem;
                --tesph-topbar-control-gap:.4rem;
                --tesph-topbar-control-inset:.7rem;
                --tesph-sidebar-toggle-size:1.45rem;
                --tesph-sidebar-toggle-top:calc(var(--tesph-topbar-height) - 2.9rem);
                --tesph-sidebar-toggle-expanded-left:calc(var(--tesph-sidebar-collapsed-width) - .9rem);
                --tesph-sidebar-toggle-collapsed-left:calc(var(--tesph-sidebar-collapsed-width) - .9rem);
            }
            .block-container { padding-left:.85rem !important; padding-right:.85rem !important; }
            .topbar-page { padding:0 .65rem !important; }
            .topbar-right { padding:0 var(--tesph-topbar-control-inset) 0 .25rem !important; }
            .topbar-title { font-size:.92rem !important; }
            .topbar-breadcrumb { display:none !important; }
            .data-status { display:none !important; }
            .topbar-admin { max-width:8rem !important; }
            div.st-key-topbar_profile button { gap:.28rem !important; padding:.22rem .42rem .22rem .24rem !important; }
            div.st-key-topbar_profile button::before { width:1.5rem; height:1.5rem; flex-basis:1.5rem; }
            div.st-key-topbar_profile button p:first-child { max-width:3.2rem; font-size:.62rem !important; }
            div.st-key-topbar_profile button p:last-child { display:none !important; }
            div.st-key-topbar_profile button::after { width:.34rem; height:.34rem; flex-basis:.34rem; }
            .topbar-panel-notifications { right:.7rem !important; }
            .topbar-panel-profile { right:.7rem !important; }
            div.st-key-topbar_logout button { padding:.38rem .52rem !important; }
            .category-mix-body { grid-template-columns:1fr; }
            .category-mix-donut { width:min(11rem, 70vw); }
        }

        @media (max-width:720px) {
            [data-testid="stHorizontalBlock"] {
                flex-wrap:wrap !important;
                gap:.75rem !important;
            }

            [data-testid="stHorizontalBlock"] > [data-testid="column"] {
                flex:1 1 100% !important;
                width:100% !important;
                min-width:100% !important;
            }

            [data-testid="stVerticalBlockBorderWrapper"] > div {
                max-width:100% !important;
            }

            .card-header,
            .etl-ready,
            .topbar-notification-head {
                align-items:flex-start !important;
                flex-wrap:wrap !important;
            }

            .kpi-card,
            [data-testid="stMetric"] {
                min-height:auto !important;
            }

            .validation-card {
                height:auto !important;
                min-height:8rem !important;
            }

            .topbar-panel {
                right:.7rem !important;
                width:calc(100vw - 1.4rem) !important;
                max-height:calc(100vh - var(--tesph-topbar-height) - 1rem) !important;
            }

            div.st-key-profile_action,
            div.st-key-logout_action {
                right:1.25rem !important;
                width:calc(100vw - 2.5rem) !important;
            }
        }

        @media (max-width:430px) {
            :root {
                --tesph-topbar-profile-width:3.1rem;
                --tesph-topbar-notification-width:2.35rem;
                --tesph-topbar-control-inset:.5rem;
                --tesph-topbar-control-gap:.28rem;
                --tesph-sidebar-toggle-size:1.35rem;
                --tesph-sidebar-toggle-top:calc(var(--tesph-topbar-height) - 2.85rem);
                --tesph-sidebar-toggle-expanded-left:calc(var(--tesph-sidebar-collapsed-width) - .85rem);
                --tesph-sidebar-toggle-collapsed-left:calc(var(--tesph-sidebar-collapsed-width) - .85rem);
            }

            .block-container { padding-left:.65rem !important; padding-right:.65rem !important; }
            .topbar-page { padding:0 .55rem !important; }
            .topbar-title { font-size:.8rem !important; }
            div.st-key-topbar_profile button { justify-content:center !important; gap:0 !important; padding:0 !important; }
            div.st-key-topbar_profile button::before { width:1.72rem; height:1.72rem; flex-basis:1.72rem; }
            div.st-key-topbar_profile button > div[data-testid="stMarkdownContainer"],
            div.st-key-topbar_profile button::after { display:none !important; }
            .topbar-panel { right:.5rem !important; width:calc(100vw - 1rem) !important; }
            div.st-key-profile_action,
            div.st-key-logout_action {
                right:.75rem !important;
                width:calc(100vw - 1.5rem) !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hide_sidebar_for_logged_out_user() -> None:
    """Hide Streamlit's otherwise-empty native sidebar before authentication."""
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        [data-testid="stSidebar"],
        [data-testid="stSidebar"][aria-expanded="true"],
        [data-testid="stSidebar"][aria-expanded="false"],
        [data-testid="stSidebar"][aria-expanded="false"]:not(:has(.tesph-sidebar-expanded)),
        [data-testid="stSidebar"]:not(:has(.tesph-sidebar-expanded)):not(:has(.tesph-sidebar-collapsed)),
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] {
            display:none !important;
            visibility:hidden !important;
            min-width:0 !important;
            width:0 !important;
            max-width:0 !important;
            transform:translateX(-100%) !important;
            border-right:0 !important;
        }
        [data-testid="stSidebarContent"],
        [data-testid="stSidebarUserContent"] {
            display:none !important;
        }
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            margin-left:0 !important;
            padding-left:0 !important;
        }
        [data-testid="stHeader"] { height:0; min-height:0; visibility:hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _status_parts(status: DataStatus) -> tuple[str, str]:
    return {DataStatus.NO_DATA: ("status-empty", "No data"), DataStatus.PROCESSING: ("status-processing", "Processing"), DataStatus.DATA_READY: ("status-ready", "Data ready")}[status]


def data_status_indicator(status: DataStatus | None = None) -> str:
    """Return the prototype-style dot and label for a shared data state."""
    style, label = _status_parts(status or get_data_status())
    return f'<span class="data-status {style}"><span class="data-dot"></span>{label}</span>'


def _toggle_sidebar_collapsed() -> None:
    st.session_state[SIDEBAR_COLLAPSED_KEY] = not st.session_state.get(SIDEBAR_COLLAPSED_KEY, False)


def render_sidebar() -> None:
    """Render the approved navigation below the application-wide top bar."""
    groups = (
        ("Overview", (("pages/dashboard.py", "Dashboard", ":material/dashboard:"),)),
        ("Data", (("pages/data_upload.py", "Data Upload & ETL", ":material/upload_file:"),)),
        (
            "Analyze",
            (
                ("pages/sales_product_analytics.py", "Sales & Product Analytics", ":material/analytics:"),
                ("pages/demand_forecast.py", "Demand Forecast", ":material/trending_up:"),
                ("pages/stock_out_risk.py", "Stock-Out Risk", ":material/warning:"),
            ),
        ),
        (
            "Decide",
            (
                ("pages/replenishment_recommendations.py", "Replenishment Recommendations", ":material/refresh:"),
                ("pages/product_prioritization.py", "Product Prioritization", ":material/format_list_numbered:"),
            ),
        ),
        (
            "Support",
            (
                ("pages/settings.py", "Settings", ":material/settings:"),
                ("pages/help_user_guide.py", "Help & User Guide", ":material/help:"),
            ),
        ),
    )
    st.session_state.setdefault(SIDEBAR_COLLAPSED_KEY, False)
    collapsed = bool(st.session_state[SIDEBAR_COLLAPSED_KEY])
    with st.sidebar:
        state_class = "tesph-sidebar-collapsed" if collapsed else "tesph-sidebar-expanded"
        st.markdown(f'<span class="{state_class}" aria-hidden="true"></span>', unsafe_allow_html=True)
        for group_index, (section, links) in enumerate(groups):
            if not collapsed:
                st.markdown(f'<div class="nav-section">{section}</div>', unsafe_allow_html=True)
            elif group_index:
                st.markdown('<span class="tesph-rail-group-start" aria-hidden="true"></span>', unsafe_allow_html=True)
            for target, label, icon in links:
                st.page_link(target, label=label, icon=icon, use_container_width=not collapsed)
        if collapsed:
            st.button("> |", key="tesph_sidebar_toggle_collapsed", help="Expand sidebar", on_click=_toggle_sidebar_collapsed)
        else:
            st.button("| <", key="tesph_sidebar_toggle_expanded", help="Collapse sidebar", on_click=_toggle_sidebar_collapsed)
        if not collapsed and get_data_status() is DataStatus.NO_DATA:
            st.markdown('<div class="nav-gate-note">Analytics and decision pages require a processed dataset. They remain available for review.</div>', unsafe_allow_html=True)


@st.dialog("Reset Password")
def _forgot_password_dialog() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stDialog"]:has(.reset-password-dialog-anchor) {
            display:flex !important;
            align-items:center !important;
            justify-content:center !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) {
            margin:auto !important;
            max-height:calc(100vh - 2rem) !important;
            overflow-y:auto !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) > h2[slot="title"] {
            padding:1.5rem 1.5rem .6rem !important;
            margin:0 !important;
            min-height:0 !important;
            height:auto !important;
            align-items:flex-start !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) > h2[slot="title"] [data-testid="stMarkdownContainer"] p {
            margin:0 !important;
            color:#252525 !important;
            font-size:1.55rem !important;
            font-weight:650 !important;
            line-height:1.2 !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) > h2[slot="title"] + div {
            padding:.5rem 1.5rem 1.5rem !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) [data-testid="stElementContainer"]:has(.reset-password-dialog-anchor) {
            display:none !important;
            height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:hidden !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) [data-testid="stVerticalBlock"] {
            gap:0 !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) [data-testid="stElementContainer"]:has(.reset-password-copy) {
            margin:0 0 1.55rem !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) [data-testid="stElementContainer"]:has([data-testid="stTextInput"]) {
            margin-bottom:.75rem !important;
        }
        section[role="dialog"]:has(.reset-password-dialog-anchor) [data-testid="stElementContainer"]:has([data-testid="stAlert"]) {
            width:100% !important;
            margin-top:.85rem !important;
        }
        .reset-password-copy {
            margin:0 !important;
            color:#252525 !important;
            font-size:.95rem !important;
            line-height:1.55 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<span class="reset-password-dialog-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    st.markdown(
        '<p class="reset-password-copy">Enter your registered email address, and we\'ll send you a link to reset your password.</p>',
        unsafe_allow_html=True,
    )
    email = st.text_input("Email Address", placeholder="Enter your email address", key="forgot_password_email")
    processing = bool(st.session_state.get("forgot_password_processing", False))
    feedback: tuple[str, str] | None = None
    left, right = st.columns((1, 1), gap="small")
    with left:
        if st.button("Cancel", use_container_width=True, disabled=processing):
            st.session_state["show_forgot_password_dialog"] = False
            st.query_params.pop("forgot_password", None)
            st.rerun()
    with right:
        if st.button("Send Reset Link", type="primary", use_container_width=True, disabled=processing):
            cleaned_email = email.strip()
            if not cleaned_email:
                feedback = ("error", "Email address is required.")
            elif EMAIL_PATTERN.match(cleaned_email) is None:
                feedback = ("error", "Enter a valid email address.")
            else:
                st.session_state["forgot_password_processing"] = True
                try:
                    result = request_password_reset(cleaned_email)
                finally:
                    st.session_state["forgot_password_processing"] = False
                if result.configured and result.requested:
                    st.session_state["show_forgot_password_dialog"] = False
                    st.query_params.pop("forgot_password", None)
                    feedback = ("success", result.message)
                else:
                    feedback = ("error", result.message)
    if feedback:
        getattr(st, feedback[0])(feedback[1])


def render_login_screen() -> None:
    """Render the local authorized-user login screen."""
    reset_token = st.query_params.get("reset_token")
    if st.query_params.get("forgot_password") == "1":
        st.session_state["show_forgot_password_dialog"] = True
    st.markdown('<div class="login-spacer"></div>', unsafe_allow_html=True)
    left, content, right = st.columns((1.2, 1, 1.2))
    with content:
        business_name = get_business_name()
        st.markdown(
            f'<div class="login-brand"><img src="{_logo_data_uri()}" alt="TheEverythingShopPH logo">'
            f'<h1 class="login-title">{html.escape(business_name)}</h1>'
            '<p class="login-subtitle">Decision Support System</p></div>',
            unsafe_allow_html=True,
        )
        if reset_token:
            with st.container(border=True):
                st.markdown('<span class="login-form-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
                st.subheader("Reset password")
                new_password = st.text_input("New Password", type="password", placeholder="Enter a new password")
                confirm_password = st.text_input("Confirm New Password", type="password", placeholder="Confirm your new password")
                if st.button("Reset Password", type="primary", use_container_width=True):
                    if new_password != confirm_password:
                        st.error("Passwords do not match.")
                    else:
                        ok, message = reset_password_with_token(str(reset_token), new_password)
                        if ok:
                            st.success(message)
                            st.query_params.clear()
                        else:
                            st.error(message)
            return
        with st.container(border=True):
            st.markdown('<span class="login-form-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
            pending_2fa_user = st.session_state.get("pending_2fa_username")
            if pending_2fa_user:
                st.markdown('<span class="two-factor-verification-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
                st.subheader("Two-factor verification")
                st.caption("Enter the 6-digit code from Google Authenticator.")
                two_factor_code = st.text_input("Authentication Code", max_chars=6, placeholder="000000")
                verify_col, cancel_col = st.columns((1, 1), gap="small")
                with verify_col:
                    if st.button("Verify", type="primary", use_container_width=True):
                        if verify_user_two_factor(str(pending_2fa_user), two_factor_code):
                            st.session_state.pop("pending_2fa_username", None)
                            start_authenticated_session(str(pending_2fa_user))
                            st.rerun()
                        st.error("Invalid authentication code.")
                with cancel_col:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state.pop("pending_2fa_username", None)
                        st.rerun()
                return
            with st.form("prototype_login_form"):
                login_error_slot = st.empty()
                username = st.text_input("Username", placeholder="Enter your username")
                password = st.text_input("Password", type="password", placeholder="Enter your password")
                st.markdown(
                    '<span class="login-options-anchor" aria-hidden="true"></span>',
                    unsafe_allow_html=True,
                )
                option_left, option_right = st.columns((1, 1), vertical_alignment="center")
                with option_left:
                    remember_me = st.checkbox("Remember Me")
                with option_right:
                    st.markdown(
                        '<div class="login-forgot-wrap"><a class="login-forgot-link" href="?forgot_password=1" target="_self">Forgot Password?</a></div>',
                        unsafe_allow_html=True,
                    )
                submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)
            if submitted:
                if not is_authentication_configured():
                    st.error("Local authorized-user access is not configured. Add the local auth configuration and restart the app.")
                elif authenticate(username.strip(), password):
                    if remember_me:
                        st.warning("Remember Me requires secure cookie support, which is not available in this local Streamlit runtime. Signing in for this session only.")
                    if is_two_factor_enabled(username.strip()):
                        st.session_state["pending_2fa_username"] = username.strip()
                        st.rerun()
                    start_authenticated_session(username.strip())
                    st.rerun()
                else:
                    login_error_slot.error("Invalid username or password.")
            if st.session_state.get("show_forgot_password_dialog"):
                _forgot_password_dialog()
        st.markdown(
            '<p class="login-note">Smarter insights for sales, demand, inventory, and replenishment decisions.</p>',
            unsafe_allow_html=True,
        )


def guard_protected_page() -> None:
    """Show the login screen when a page is opened outside the main router."""
    initialize_app_state()
    if not is_authenticated():
        inject_global_styles()
        hide_sidebar_for_logged_out_user()
        render_login_screen()
        st.stop()


def _session_timeout_reload_timer() -> None:
    """Refresh the browser when inactivity timeout should be evaluated."""
    last_activity = st.session_state.get("_last_activity_time")
    if last_activity is None:
        return
    timeout_seconds = get_session_timeout_minutes() * 60
    remaining_seconds = float(last_activity) + timeout_seconds - time.time()
    delay_ms = max(1_000, int(remaining_seconds * 1_000) + 1_000)
    st_components.html(
        f"""
        <script>
        window.setTimeout(() => {{
            window.parent.location.reload();
        }}, {delay_ms});
        </script>
        """,
        height=0,
        width=0,
    )


def render_page_shell(title: str, breadcrumb: str) -> None:
    """Render the Figma-inspired topbar consistently on every approved page."""
    _session_timeout_reload_timer()
    st.session_state.pop("show_logout_dialog", None)
    current_page = f"{breadcrumb}:{title}"
    if st.session_state.get("_topbar_active_page") != current_page:
        st.session_state["show_notifications_panel"] = False
        st.session_state["show_profile_menu"] = False
        if title != "Settings":
            for key in (
                "show_edit_profile_dialog",
                "show_change_password_dialog",
                "show_two_factor_dialog",
                "open_profile_from_topbar",
                "profile_full_name",
            ):
                st.session_state.pop(key, None)
        st.session_state["_topbar_active_page"] = current_page
    generate_system_notifications()
    topbar_state_class = "tesph-topbar-collapsed" if st.session_state.get(SIDEBAR_COLLAPSED_KEY, False) else "tesph-topbar-expanded"
    business_name = html.escape(get_business_name())
    username = str(st.session_state.get("authenticated_username") or "")
    profile = get_account_profile(username) if username else None
    raw_name = profile.full_name if profile is not None else username or "Administrator"
    display_name = html.escape(raw_name)
    initials = "".join(part[0] for part in raw_name.replace("_", " ").replace("-", " ").split()[:2]).upper()
    initials = "".join(character for character in (initials or raw_name[:2] or "AD") if character.isalnum())[:2].upper() or "AD"
    count = unread_count()
    st.markdown(
        f'<div class="tesph-topbar-spacer" aria-hidden="true"></div>'
        f'<style>div.st-key-topbar_notifications button::after {{ content:"{count}"; display:{"block" if count else "none"}; position:absolute; top:.12rem; right:.05rem; min-width:1rem; height:1rem; padding:0 .25rem; box-sizing:border-box; border:1px solid rgba(255,255,255,.75); border-radius:999px; background:#B84F3F; color:#FFFFFF; font-size:.64rem; font-weight:800; line-height:.9rem; text-align:center; }} div.st-key-topbar_profile button::before {{ content:"{initials}"; }}</style>'
        f'<header class="tesph-topbar {topbar_state_class}">'
        f'<div class="topbar-brand"><img src="{_logo_data_uri()}" alt="{business_name} logo"><div><div class="topbar-brand-name">{business_name}</div><div class="topbar-brand-subtitle">Decision Support</div></div></div>'
        f'<div class="topbar-page"><div class="topbar-breadcrumb">{breadcrumb}</div><div class="topbar-title">{title}</div></div>'
        f'<div class="topbar-right">{data_status_indicator()}<div class="topbar-divider"></div><div class="topbar-control-reservation" aria-hidden="true"></div></div>'
        f'</header>',
        unsafe_allow_html=True,
    )
    if st.button("", key="topbar_notifications", help="Notifications", icon=":material/notifications:"):
        st.session_state["show_notifications_panel"] = not st.session_state.get("show_notifications_panel", False)
        st.session_state["show_profile_menu"] = False
    if st.button(f"**{display_name}**\n\nAdministrator", key="topbar_profile", help=f"Profile menu for {raw_name}"):
        st.session_state["show_profile_menu"] = not st.session_state.get("show_profile_menu", False)
        st.session_state["show_notifications_panel"] = False
    if st.session_state.get("show_notifications_panel"):
        notifications = get_all_notifications()
        if notifications:
            items = []
            for item in notifications[:5]:
                title_html = html.escape(str(item.get("title") or "Notification"))
                message_html = html.escape(str(item.get("message") or ""))
                time_html = html.escape(format_notification_time(str(item.get("timestamp") or "")))
                items.append(
                    '<div class="topbar-notification-item">'
                    f'<div class="topbar-notification-head"><span>{title_html}</span><span class="topbar-notification-time">{time_html}</span></div>'
                    f'<div class="topbar-notification-copy" style="font-size:.68rem;line-height:1.35;">{message_html}</div></div>'
                )
            st.markdown(
                '<div class="topbar-panel topbar-panel-notifications"><div class="topbar-panel-title">Notifications</div>'
                + "".join(items)
                + "</div>",
                unsafe_allow_html=True,
            )
            mark_all_read()
        else:
            st.markdown(
                '<div class="topbar-panel topbar-panel-notifications"><div class="topbar-panel-title">Notifications</div>'
                '<div class="topbar-empty">No ETL processing, data freshness, or stock-out risk notifications are available.</div></div>',
                unsafe_allow_html=True,
            )
    if st.session_state.get("show_profile_menu"):
        st.markdown(
            '<div class="topbar-panel topbar-panel-profile">'
            '<div class="topbar-profile-head">'
            f'<div class="topbar-profile-avatar">{initials}</div>'
            '<div>'
            f'<div class="topbar-profile-name">{display_name}</div>'
            '<div class="topbar-profile-role">Administrator</div>'
            '</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("Edit Profile", key="profile_action", use_container_width=True):
            st.session_state["show_profile_menu"] = False
            st.session_state["show_notifications_panel"] = False
            st.session_state["open_profile_from_topbar"] = True
            st.switch_page("pages/settings.py")
        if st.button("Log Out", key="logout_action", use_container_width=True):
            st.session_state["show_profile_menu"] = False
            st.session_state["show_notifications_panel"] = False
            _logout_dialog()


@st.dialog("Log Out")
def _logout_dialog() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stDialog"]:has(.logout-dialog-anchor) {
            display:flex !important;
            align-items:center !important;
            justify-content:center !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) {
            margin:auto !important;
            width:25rem !important;
            max-width:calc(100vw - 2rem) !important;
            border-radius:8px !important;
            overflow:hidden !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) > h2[slot="title"] {
            height:0 !important;
            min-height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:hidden !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) > h2[slot="title"] [data-testid="stMarkdownContainer"] {
            display:none !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) > h2[slot="title"] + div {
            padding:1.05rem 1.25rem 1.15rem !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) [data-testid="stVerticalBlock"] {
            gap:0 !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) [data-testid="stElementContainer"]:has(.logout-dialog-anchor) {
            display:none !important;
            height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:hidden !important;
        }
        section[role="dialog"]:has(.logout-dialog-anchor) [data-testid="stElementContainer"]:has(.logout-dialog-body) {
            margin:0 !important;
            padding:0 !important;
        }
        .logout-dialog-body {
            display:flex;
            flex-direction:column;
            align-items:center;
            margin:0 !important;
            padding:0 !important;
            text-align:center;
        }
        .logout-dialog-icon {
            display:grid;
            place-items:center;
            width:3.125rem;
            height:3.125rem;
            align-self:center;
            margin:0 0 .75rem;
            border-radius:999px;
            background:#FEF7E7;
            color:#D9980F;
        }
        .logout-dialog-title {
            margin:0 0 .62rem !important;
            color:#252525 !important;
            font-size:1.05rem !important;
            font-weight:850 !important;
            line-height:1.25 !important;
            text-align:center !important;
        }
        .logout-dialog-copy {
            max-width:18rem;
            margin:0 auto .18rem !important;
            color:#625C54 !important;
            font-size:.72rem !important;
            line-height:1.35 !important;
            text-align:center !important;
        }
        .logout-dialog-copy:last-child { margin-bottom:.75rem !important; }
        section[role="dialog"]:has(.logout-dialog-anchor) [data-testid="stHorizontalBlock"] {
            gap:.75rem !important;
            margin-top:1.05rem !important;
        }
        div.st-key-cancel_logout button,
        div.st-key-confirm_logout button {
            min-height:2.35rem !important;
            border-radius:6px !important;
            font-size:.78rem !important;
            font-weight:600 !important;
            box-shadow:none !important;
        }
        div.st-key-cancel_logout button {
            border-color:#D8D2C9 !important;
            background:#FFFFFF !important;
            color:#252525 !important;
        }
        div.st-key-confirm_logout button {
            border-color:#D9980F !important;
            background:#D9980F !important;
            color:#1F1A12 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<span class="logout-dialog-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="logout-dialog-body">
            <div class="logout-dialog-icon">{icon_svg("log_out", size=22, color="#D9980F")}</div>
            <p class="logout-dialog-title">Log Out</p>
            <p class="logout-dialog-copy">Are you sure you want to log out?</p>
            <p class="logout-dialog-copy">You will need to sign in again to access<br>TheEverythingShopPH.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cancel_col, logout_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", key="cancel_logout", use_container_width=True):
            st.rerun()
    with logout_col:
        if st.button("Log Out", key="confirm_logout", type="primary", use_container_width=True):
            logout()
            st.rerun()


def card_header(
    title: str,
    subtitle: str | None = None,
    right_text: str | None = None,
    class_name: str | None = None,
) -> None:
    """Render a shared card heading and divider."""
    subtitle_html = f'<p class="card-subtitle">{subtitle}</p>' if subtitle else ""
    right = f'<span class="card-subtitle">{right_text}</span>' if right_text else ""
    header_class = f"card-header {class_name}" if class_name else "card-header"
    st.markdown(f'<div class="{header_class}"><div><h3 class="card-title">{title}</h3>{subtitle_html}</div>{right}</div>', unsafe_allow_html=True)


def section_header(title: str, description: str | None = None) -> None:
    """Render a page section without unnecessarily boxing the content."""
    description_html = f'<p class="section-description">{description}</p>' if description else ""
    st.markdown(f'<h2 class="section-title">{title}</h2>{description_html}', unsafe_allow_html=True)


def kpi_card(label: str, value: str | None = None, accent: bool = False) -> None:
    """Render a KPI or a no-data skeleton without fabricated values."""
    marker = '<span style="display:inline-block;width:4px;height:14px;margin-right:8px;border-radius:3px;background:var(--tesph-brand);vertical-align:-2px"></span>' if accent else ""
    content = f'<div class="kpi-value">{value}</div>' if value is not None else '<div class="kpi-skeleton"></div>'
    st.markdown(f'<div class="kpi-card"><div class="kpi-label">{marker}{label}</div>{content}</div>', unsafe_allow_html=True)


def primary_button(label: str, *, key: str | None = None, disabled: bool = False) -> bool:
    return st.button(label, key=key, type="primary", disabled=disabled, use_container_width=True)


def secondary_button(label: str, *, key: str | None = None, disabled: bool = False) -> bool:
    return st.button(label, key=key, type="secondary", disabled=disabled, use_container_width=True)


def badge(label: str, tone: str = "neutral") -> str:
    class_name = {"high": "badge-high", "medium": "badge-medium", "low": "badge-low"}.get(tone, "badge-neutral")
    return f'<span class="status-badge {class_name}">{label}</span>'


def empty_state(title: str, message: str, icon: str = "○") -> None:
    st.markdown(f'<section class="empty-panel"><div class="empty-icon">{icon}</div><h2 class="empty-title">{title}</h2><p class="empty-copy">{message}</p></section>', unsafe_allow_html=True)


def data_required_state(module_name: str) -> None:
    """Render a shared no-data gate while preserving access to each approved page."""
    if get_data_status() is DataStatus.DATA_READY:
        empty_state(f"{module_name} integration pending", "A processed dataset is available. This module will display approved results once its analytics integration is connected.", "◌")
    else:
        empty_state("No dataset available", "Upload and process Shopee transaction data to begin analysis.", "⌁")


def render_upload_summary(filename: str) -> None:
    st.markdown(
        f"""
        <div class="upload-summary">
            <div class="upload-summary-name">{filename}</div>
            <div class="upload-summary-meta">
                XLSX selected · Pending ETL validation · No rows have been read
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def schema_placeholder(prepared_transactions: Any | None = None, star_schema: dict[str, Any] | None = None):
    def schema_rows(table_name: str, table: Any) -> list[dict[str, str]]:
        rows = []

        for column in getattr(table, "columns", []):
            rows.append(
                {
                    "Column": str(column),
                    "Type": str(table[column].dtype),
                }
            )

        return rows

    if prepared_transactions is None or getattr(prepared_transactions, "empty", True):
        st.markdown(
            """
            <span class="schema-card-marker" aria-hidden="true"></span>
            <div class="schema-placeholder" style="margin: 1rem;">
                <div class="schema-copy">
                    The ETL module will validate source columns and report an explicit mapping after processing.
                    No source fields are assumed here.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    prepared_rows = schema_rows("prepared_transactions", prepared_transactions)
    st.markdown(
        f"""
        <span class="schema-card-marker" aria-hidden="true"></span>
        <div class="schema-placeholder" style="margin: 1rem;">
            <div class="schema-copy">
                Prepared transactions: {len(prepared_rows):,} validated columns.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.dataframe(
        prepared_rows,
        use_container_width=True,
        hide_index=True,
        height=298,
    )

def etl_stepper(message: str | None = None) -> None:
    """Render ETL stages as reported by the real orchestrator."""
    status, active_step = get_data_status(), get_etl_active_step()
    if status is DataStatus.PROCESSING and active_step is None:
        active_step = 0
    step_html: list[str] = []
    for index, (name, description) in enumerate(ETL_STEPS):
        done = status is DataStatus.DATA_READY or (active_step is not None and index < active_step)
        active = status is DataStatus.PROCESSING and index == active_step
        modifier = " etl-step-done" if done else " etl-step-active" if active else ""
        marker = "✓" if done else str(index + 1)
        step_html.append(f'<div class="etl-step{modifier}"><div class="etl-number">{marker}</div><div class="etl-name">{name}</div><p class="etl-copy">{description}</p></div>')
    st.markdown(f'<div class="etl-grid">{"".join(step_html)}</div>', unsafe_allow_html=True)
    if status is DataStatus.PROCESSING:
        st.markdown(
            f'<div class="processing-panel"><p class="state-title">Processing data</p>'
            f'<p class="state-copy">{message or "The ETL pipeline is working on the current stage."}</p></div>',
            unsafe_allow_html=True,
        )
    if status is DataStatus.DATA_READY:
        st.markdown(f'<div class="etl-ready"><div><div class="etl-ready-title">Data ready</div><div class="etl-ready-copy">A validated canonical dataset is available for connected modules.</div></div>{data_status_indicator(status)}</div>', unsafe_allow_html=True)


def data_table_container(data: Any, column_order: Sequence[str] | None = None) -> None:
    with st.container(border=True):
        st.dataframe(data, column_order=column_order, use_container_width=True, hide_index=True)


def info_message(message: str) -> None:
    st.markdown(f'<div class="info-message">{message}</div>', unsafe_allow_html=True)


def success_state(message: str, metrics: Sequence[str] = ()) -> None:
    """Show a concise successful-processing confirmation."""
    metric_html = "".join(f'<span class="success-metric">{metric}</span><br>' for metric in metrics)
    st.markdown(
        f'<div class="success-panel"><p class="state-title">Data processed successfully</p>'
        f'<p class="state-copy">{message}</p>{metric_html}</div>',
        unsafe_allow_html=True,
    )


def validation_error_state(issues: Sequence[str]) -> None:
    """Present ETL-provided validation failures in user-facing language."""
    count = len(issues)
    issue_html = "".join(f'<li>{html.escape(str(issue))}</li>' for issue in issues)
    st.markdown(
        f'<div class="validation-panel"><p class="state-title">Data validation needs attention</p>'
        f'<p class="state-copy">We found {count} issue{"s" if count != 1 else ""} in the uploaded file. Fix the items below and upload it again.</p>'
        f'<ul class="validation-list">{issue_html}</ul></div>',
        unsafe_allow_html=True,
    )


def persistence_error_state() -> None:
    """Explain that validated data could not be saved without blaming the file."""
    st.markdown(
        '<div class="validation-panel"><p class="state-title">Data validated, but not saved</p>'
        '<p class="state-copy">The uploaded data passed validation, but the system could not save the processed data because the database is temporarily unavailable. The active dataset was not changed. Please retry shortly.</p></div>',
        unsafe_allow_html=True,
    )
