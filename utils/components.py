"""Shared Streamlit presentation components for the TESPH DSS foundation."""

import base64
import html
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import streamlit as st

from utils.auth import (
    authenticate,
    is_authentication_configured,
    is_authenticated,
    logout,
    start_authenticated_session,
)
from utils.state import DataStatus, get_data_status, get_etl_active_step, initialize_app_state


LOGO_PATH = "assets/theeverythingshopph-logo.png"
ETL_STEPS = (
    ("Ingest", "Receive the selected Shopee export"),
    ("Clean", "Check duplicate and missing source values"),
    ("Validate", "Check date, numeric, and financial values"),
    ("Transform", "Build canonical transactions and star schema"),
    ("Load", "Hand validated outputs to session and database"),
)


@st.cache_data(show_spinner=False)
def _logo_data_uri() -> str:
    """Embed the unmodified local logo in custom sidebar markup."""
    encoded = base64.b64encode(Path(LOGO_PATH).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def inject_global_styles() -> None:
    """Apply the Figma-derived, light warm visual system across Streamlit."""
    st.markdown(
        """
        <style>
        :root { --tesph-canvas:#FFFDF8; --tesph-surface:#FFF; --tesph-ink:#252525; --tesph-ink-soft:#66615A; --tesph-ink-faint:#8A8379; --tesph-line:#EDE7DC; --tesph-line-strong:#E0D8CF; --tesph-amber:#EEAC17; --tesph-amber-hover:#D49A12; --tesph-amber-tint:#FFFAE8; --tesph-amber-soft:#FFF3A6; --tesph-peach:#F8DEC5; --tesph-green:#E8F3EC; }
        .stApp,[data-testid="stAppViewContainer"] { background:var(--tesph-canvas); color:var(--tesph-ink); } html,body,[class*="css"] { font-family:Inter,"Segoe UI",Arial,sans-serif; } [data-testid="stHeader"], [data-testid="stToolbar"] { background:transparent; pointer-events:none; } [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"] { display:none !important; } [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapseButton"] { pointer-events:auto !important; }
        [data-testid="stSidebar"][aria-expanded="true"], [data-testid="stSidebar"]:not([aria-expanded="false"]) { min-width:19.5rem !important; width:19.5rem !important; background:var(--tesph-surface); border-right:1px solid var(--tesph-line); } [data-testid="stSidebar"][aria-expanded="false"] { min-width:0 !important; width:0 !important; border-right:none !important; } [data-testid="stSidebar"] > div:first-child { padding-top:0; } [data-testid="stSidebarCollapseButton"] { visibility:visible !important; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] { min-height:2.75rem; border-radius:.4rem; margin:.12rem .72rem; padding:.52rem .65rem; color:var(--tesph-ink-soft); font-size:.88rem; } [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover { background:var(--tesph-amber-tint); color:var(--tesph-ink); } [data-testid="stSidebar"] [aria-current="page"] { position:relative; background:var(--tesph-amber-tint); color:var(--tesph-ink); font-weight:600; } [data-testid="stSidebar"] [aria-current="page"]::before { content:""; position:absolute; left:0; top:50%; transform:translateY(-50%); width:2px; height:1.35rem; border-radius:0 4px 4px 0; background:var(--tesph-amber); }
        .block-container { max-width:none; padding:0 2rem 2.5rem; }.tesph-brand-panel { display:flex; align-items:center; gap:.68rem; min-height:5.45rem; padding:.9rem 1.25rem; background:var(--tesph-amber); border-bottom:1px solid #c89a12; }.tesph-brand-panel img { width:2.3rem; height:2.3rem; object-fit:contain; border:1px solid rgba(26,18,8,.18); border-radius:.38rem; background:#fff; padding:.16rem; }.tesph-brand-name { color:#1a1208; font-size:.9rem; font-weight:700; line-height:1.2; }.tesph-brand-subtitle { color:#3d2810; font-size:.68rem; margin-top:.08rem; }.nav-section { margin:1.22rem 1.45rem .33rem; color:var(--tesph-ink-faint); font-size:.64rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; }.nav-gate-note { margin:.85rem 1.45rem 1rem; color:var(--tesph-ink-faint); font-size:.68rem; line-height:1.45; }
        .tesph-topbar { display:flex; align-items:center; justify-content:space-between; gap:1rem; min-height:5.45rem; margin:0 -2rem 1.65rem; padding:.82rem 2rem; background:var(--tesph-amber); border-bottom:1px solid #c89a12; color:#1a1208; }.topbar-breadcrumb { color:#3d2810; font-size:.68rem; margin-bottom:.15rem; }.topbar-title { color:#1a1208; font-size:1.16rem; font-weight:700; line-height:1.2; }.topbar-right { display:flex; align-items:center; gap:.85rem; }.topbar-divider { width:1px; height:1.6rem; background:rgba(26,18,8,.24); }.topbar-person { text-align:right; line-height:1.2; }.topbar-name { font-size:.85rem; font-weight:600; }.topbar-role { color:#3d2810; font-size:.66rem; }.topbar-avatar { display:grid; place-items:center; width:2rem; height:2rem; background:#fff; border-radius:50%; font-size:.7rem; font-weight:700; }.logout-affordance { display:grid; place-items:center; color:#1a1208; font-size:1rem; padding-left:.12rem; }
        .data-status { display:inline-flex; align-items:center; gap:.43rem; color:#1a1208; font-size:.76rem; font-weight:500; white-space:nowrap; }.data-dot { width:.52rem; height:.52rem; border-radius:50%; }.status-empty .data-dot { background:#c8c4bc; }.status-processing .data-dot { background:#d4904a; animation:tesph-pulse 1.2s infinite; }.status-ready .data-dot { background:#3d7a53; }
        [data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--tesph-line) !important; border-radius:.5rem !important; background:var(--tesph-surface); }.card-header { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding:.84rem 1.15rem; border-bottom:1px solid var(--tesph-line); }.card-title { margin:0; color:var(--tesph-ink); font-size:.95rem; font-weight:700; }.card-subtitle { margin:.16rem 0 0; color:var(--tesph-ink-faint); font-size:.75rem; }.section-heading { margin:0 0 .8rem; color:var(--tesph-ink); font-size:1rem; font-weight:700; }.section-copy { margin:-.45rem 0 1rem; color:var(--tesph-ink-faint); font-size:.78rem; }
        .kpi-card { min-height:6.8rem; padding:1rem 1.08rem; border:1px solid var(--tesph-line); border-radius:.5rem; background:var(--tesph-surface); }.kpi-label { color:var(--tesph-ink-faint); font-size:.68rem; font-weight:600; letter-spacing:.035em; text-transform:uppercase; }.kpi-skeleton { width:4.8rem; height:1.55rem; margin-top:.75rem; border-radius:.25rem; background:var(--tesph-line); }.kpi-value { margin-top:.45rem; color:var(--tesph-ink); font-size:1.55rem; font-weight:700; }
        .empty-panel { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:18rem; padding:3rem 1.5rem; border:1px dashed var(--tesph-line-strong); border-radius:.5rem; background:var(--tesph-surface); text-align:center; }.empty-icon { display:grid; place-items:center; width:3rem; height:3rem; border-radius:.5rem; background:var(--tesph-canvas); color:var(--tesph-ink-faint); font-size:1.25rem; }.empty-title { margin:1rem 0 .4rem; color:var(--tesph-ink); font-size:1.05rem; font-weight:700; }.empty-copy { max-width:25rem; margin:0; color:var(--tesph-ink-soft); font-size:.85rem; line-height:1.5; }
        .status-badge { display:inline-flex; align-items:center; gap:.3rem; border:1px solid var(--tesph-line); border-radius:.3rem; padding:.22rem .48rem; font-size:.72rem; font-weight:600; }.badge-high { background:var(--tesph-peach); color:#8c4a15; border-color:#f0ccb0; }.badge-medium { background:var(--tesph-amber-soft); color:#7a5e12; border-color:#edd988; }.badge-low { background:var(--tesph-green); color:#3d7a53; border-color:#c8e0d0; }.badge-neutral { background:#fff9d9; color:var(--tesph-ink-soft); }
        .upload-zone { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:13.4rem; padding:1.5rem; border:2px dashed var(--tesph-line-strong); border-radius:.5rem; background:var(--tesph-canvas); text-align:center; }.upload-zone-title { margin:.55rem 0 .18rem; color:var(--tesph-ink); font-size:.88rem; font-weight:600; }.upload-zone-copy { margin:0; color:var(--tesph-ink-faint); font-size:.73rem; }[data-testid="stFileUploader"] { width:min(100%,25rem); margin-top:.8rem; border:0; background:transparent; }.uploadedFile { border-color:var(--tesph-line-strong) !important; background:#fff !important; }.upload-summary { display:flex; align-items:center; gap:.75rem; margin:1.15rem; padding:.85rem; border:1px solid var(--tesph-line); border-radius:.5rem; background:var(--tesph-canvas); }.file-icon { display:grid; place-items:center; flex:0 0 auto; width:2.25rem; height:2.25rem; border:1px solid var(--tesph-line); border-radius:.35rem; background:#fff; color:var(--tesph-ink-soft); }.file-name { color:var(--tesph-ink); font-size:.84rem; font-weight:600; }.file-meta { margin-top:.12rem; color:var(--tesph-ink-faint); font-size:.71rem; }.schema-placeholder { padding:1.05rem 1.15rem 1.2rem; }.schema-icon { color:var(--tesph-ink-faint); font-size:1.1rem; }.schema-title { margin:.45rem 0 .2rem; color:var(--tesph-ink-soft); font-size:.82rem; font-weight:600; }.schema-copy { max-width:18rem; margin:0; color:var(--tesph-ink-faint); font-size:.74rem; line-height:1.48; }
        .etl-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.7rem; padding:1.15rem; }.etl-step { min-height:8.1rem; padding:.85rem; border:1px solid var(--tesph-line); border-radius:.5rem; background:var(--tesph-canvas); }.etl-step-active { border-color:#e8d8a0; background:var(--tesph-amber-tint); }.etl-step-done { border-color:#c8e0d0; background:#edf7f0; }.etl-number { display:grid; place-items:center; width:1.45rem; height:1.45rem; border-radius:50%; background:var(--tesph-line-strong); color:#fff; font-size:.67rem; font-weight:700; }.etl-step-active .etl-number { background:var(--tesph-amber); color:#222; }.etl-step-done .etl-number { background:#3d7a53; }.etl-name { margin-top:.72rem; color:var(--tesph-ink); font-size:.78rem; font-weight:600; }.etl-copy { margin:.3rem 0 0; color:var(--tesph-ink-faint); font-size:.67rem; line-height:1.35; }.etl-ready { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin:0 1.15rem 1.15rem; padding:.85rem 1rem; border:1px solid #c8e0d0; border-radius:.5rem; background:#edf7f0; }.etl-ready-title { color:#3d7a53; font-size:.82rem; font-weight:700; }.etl-ready-copy { margin-top:.12rem; color:var(--tesph-ink-soft); font-size:.72rem; }.info-message { margin-top:1rem; padding:.72rem .85rem; border-left:3px solid var(--tesph-amber); border-radius:0 .4rem .4rem 0; background:#fff8e7; color:#685319; font-size:.78rem; }
        .stButton > button { min-height:2.45rem; border-radius:.38rem; font-size:.84rem; font-weight:600; }.stButton > button[kind="primary"] { border-color:var(--tesph-amber); background:var(--tesph-amber); color:#222; }.stButton > button[kind="primary"]:hover { border-color:var(--tesph-amber-hover); background:var(--tesph-amber-hover); color:#222; }.stButton > button[kind="secondary"] { border-color:var(--tesph-line-strong); background:var(--tesph-surface); color:var(--tesph-ink); }[data-testid="stTextInput"] input { border-color:var(--tesph-line-strong); border-radius:.38rem; color:var(--tesph-ink); }[data-testid="stTextInput"] input:focus { border-color:var(--tesph-amber); box-shadow:0 0 0 1px var(--tesph-amber); }.login-spacer { height:clamp(2rem,10vh,8rem); }.login-brand { display:flex; flex-direction:column; align-items:center; text-align:center; margin-bottom:1.45rem; }.login-brand img { width:4rem; height:4rem; object-fit:contain; border:1px solid var(--tesph-line); border-radius:.5rem; background:#fff; padding:.3rem; }.login-title { margin:.85rem 0 .16rem; color:var(--tesph-ink); font-size:1.24rem; font-weight:700; }.login-subtitle { margin:0; color:var(--tesph-ink-soft); font-size:.9rem; }.login-note { margin:1.5rem auto 0; max-width:30rem; color:var(--tesph-ink-faint); font-size:.73rem; line-height:1.45; text-align:center; }.login-form-note { margin:0 0 .9rem; color:var(--tesph-ink-faint); font-size:.72rem; line-height:1.4; }@keyframes tesph-pulse { 0%,100% { opacity:1; } 50% { opacity:.35; } }@media (max-width:900px) { .block-container { padding:0 1rem 2rem; }.tesph-topbar { margin:0 -1rem 1.2rem; padding:.75rem 1rem; min-height:4.5rem; }.topbar-person,.topbar-divider { display:none; }.etl-grid { grid-template-columns:1fr; }.etl-step { min-height:auto; }.kpi-card { min-height:5.8rem; } }
        /* Shared UI fidelity and readability corrections */
        [data-testid="stAppViewContainer"] { min-height:100vh; }
        [data-testid="stSidebar"][aria-expanded="true"], [data-testid="stSidebar"]:not([aria-expanded="false"]) { min-width:19.5rem !important; width:19.5rem !important; background:#FFFFFF !important; border-right:1px solid var(--tesph-line) !important; }
        [data-testid="stSidebar"][aria-expanded="false"] { min-width:0 !important; width:0 !important; border-right:none !important; }
        [data-testid="stSidebar"] > div:first-child, [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] { padding-top:0 !important; }
        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.tesph-brand-panel) { margin:0 !important; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] { display:flex !important; align-items:center !important; min-height:2.75rem !important; margin:.12rem .75rem !important; padding:.55rem .7rem !important; border-radius:.4rem !important; color:#514B43 !important; font-size:.875rem !important; font-weight:500 !important; line-height:1.3 !important; opacity:1 !important; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] * { color:inherit !important; opacity:1 !important; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] svg { stroke:currentColor !important; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover { background:var(--tesph-amber-tint) !important; color:#252525 !important; }
        [data-testid="stSidebar"] [aria-current="page"] { background:var(--tesph-amber-tint) !important; color:#252525 !important; font-weight:600 !important; }
        [data-testid="stSidebar"] [aria-current="page"]::before { width:3px !important; height:1.55rem !important; background:var(--tesph-amber) !important; }
        .tesph-brand-panel { box-sizing:border-box; height:4.5rem; min-height:4.5rem; padding:.75rem 1.25rem; gap:.65rem; }
        .tesph-brand-panel img { width:2.25rem; height:2.25rem; flex:0 0 2.25rem; }
        .tesph-brand-name { font-size:.875rem; color:#1A1208 !important; }
        .tesph-brand-subtitle { font-size:.6875rem; color:#3D2810 !important; }
        .nav-section { margin:1.15rem 1.5rem .38rem; color:#756E65 !important; font-size:.625rem; line-height:1.2; }
        .nav-gate-note { margin:1rem 1.5rem; color:#625C54 !important; font-size:.7rem; line-height:1.45; }

        .tesph-topbar { box-sizing:border-box; height:4.5rem; min-height:4.5rem; margin:0 -2rem 1.5rem; padding:.75rem 2rem; }
        .tesph-topbar > div:first-child { min-width:0; }
        .topbar-breadcrumb { color:#3D2810 !important; font-size:.6875rem; }
        .topbar-title { overflow:hidden; color:#1A1208 !important; font-size:1.125rem; text-overflow:ellipsis; white-space:nowrap; }
        .topbar-right { flex:0 0 auto; gap:.8rem; }
        .topbar-name, .data-status, .logout-affordance { color:#1A1208 !important; }
        .topbar-role { color:#3D2810 !important; }
        .topbar-avatar { width:2rem; height:2rem; flex:0 0 2rem; color:#1A1208 !important; }
        .logout-affordance { min-height:2rem; padding:.35rem .45rem; border-radius:.35rem; font-size:.75rem; font-weight:600; line-height:1; text-decoration:none; }
        .logout-affordance:hover { background:rgba(26,18,8,.10); }

        [data-testid="stTextInput"] label, [data-testid="stTextInput"] label span { color:#514B43 !important; font-size:.75rem !important; font-weight:600 !important; }
        [data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stTextInput"] input { background:#FFFFFF !important; color:#252525 !important; }
        [data-testid="stTextInput"] [data-baseweb="input"] { min-height:2.625rem; border:1px solid var(--tesph-line-strong) !important; border-radius:.4rem !important; box-shadow:none !important; }
        [data-testid="stTextInput"] [data-baseweb="input"]:focus-within { border-color:var(--tesph-amber) !important; box-shadow:0 0 0 2px rgba(238,172,23,.18) !important; }
        [data-testid="stTextInput"] input { -webkit-text-fill-color:#252525 !important; }
        [data-testid="stTextInput"] input::placeholder { color:#827A70 !important; opacity:1 !important; -webkit-text-fill-color:#827A70 !important; }
        [data-testid="stTextInput"] button { color:#625C54 !important; }
        [data-testid="stTextInput"] button:hover { color:#252525 !important; background:#FFFAE8 !important; }
        [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] { background:#FFFFFF !important; }
        [data-testid="stFormSubmitButton"] > button, .stButton > button[kind="primary"] { border-color:var(--tesph-amber) !important; background:var(--tesph-amber) !important; color:#1A1208 !important; }
        [data-testid="stFormSubmitButton"] > button:hover, .stButton > button[kind="primary"]:hover { border-color:var(--tesph-amber-hover) !important; background:var(--tesph-amber-hover) !important; color:#1A1208 !important; }
        .stButton > button[kind="secondary"] { border-color:var(--tesph-line-strong) !important; background:#FFFFFF !important; color:#3D3832 !important; }
        .stButton > button:disabled { background:#F4EFE6 !important; border-color:var(--tesph-line) !important; color:#827A70 !important; opacity:1 !important; }

        /* Login page — isolated styling so the authenticated application is unchanged. */
        .login-spacer { height:clamp(4rem, 12.3vh, 7rem); }
        .login-brand { margin-bottom:1.45rem; }
        .login-brand img { width:7rem; height:7rem; padding:.42rem; border-radius:.75rem; }
        .login-title { margin:.95rem 0 .14rem; color:#252525 !important; font-size:1.25rem; line-height:1.2; }
        .login-subtitle { color:#5D5750 !important; font-size:1rem; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) { border-color:var(--tesph-line) !important; border-radius:.7rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) > div { padding:2rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stForm"] { border:0 !important; padding:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] { margin-bottom:.9rem; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] label,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] label span { font-size:.84rem !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] [data-baseweb="input"] { min-height:3.1rem; border:1px solid #E0D8CF !important; border-radius:.55rem !important; background:#FFFFFF !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] input { background:#FFFFFF !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] button,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] button:hover,
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stTextInput"] button:focus { background:#FFFFFF !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.login-form-anchor) [data-testid="stFormSubmitButton"] > button { min-height:3.1rem !important; margin-top:.1rem; border-radius:.55rem !important; font-size:1rem !important; }
        .login-note { margin-top:1.7rem; color:#625C54 !important; font-size:.84rem; }
        @media (max-width:700px) {
          .login-spacer { height:3rem; }
          .login-brand img { width:5rem; height:5rem; }
          .login-title { font-size:1.3rem; }
        }
        .kpi-card { min-height:6.7rem; border-color:var(--tesph-line) !important; background:#FFFFFF !important; }
        .kpi-label { color:#625C54 !important; }
        .kpi-skeleton { background:#EEE8DE !important; }
        .empty-panel { min-height:17rem; border-color:var(--tesph-line-strong) !important; background:#FFFFFF !important; }
        .empty-icon { color:#625C54 !important; background:#FFFAE8 !important; }
        .empty-title { color:#252525 !important; }
        .empty-copy { color:#5D5750 !important; }
        .card-subtitle, .upload-zone-copy, .schema-copy, .file-meta { color:#625C54 !important; }
        [data-testid="stCaptionContainer"] { color:#625C54 !important; }
        .upload-zone { border-color:var(--tesph-line-strong) !important; background:var(--tesph-canvas) !important; }
        [data-testid="stFileUploaderDropzone"] { border-color:var(--tesph-line-strong) !important; background:var(--tesph-canvas) !important; }
        [data-testid="stFileUploaderDropzone"] * { color:#514B43 !important; }
        [data-testid="stFileUploaderDropzone"] button { border-color:var(--tesph-line-strong) !important; background:#FFFFFF !important; color:#3D3832 !important; }

        @media (max-width:900px) {
          [data-testid="stSidebar"][aria-expanded="true"], [data-testid="stSidebar"]:not([aria-expanded="false"]) { min-width:19.5rem !important; width:19.5rem !important; }
          .tesph-topbar { margin:0 -1rem 1.25rem; padding:.75rem 1rem; }
          .topbar-person, .topbar-divider { display:none; }
          .topbar-right { gap:.45rem; }
        }

        /* Single full-width application header: brand belongs to the top bar. */
        section[data-testid="stSidebar"] { top:4.5rem !important; height:calc(100vh - 4.5rem) !important; }
        [data-testid="stSidebar"] [data-testid="stSidebarContent"], [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top:0 !important; }
        .tesph-topbar-spacer { height:4.5rem; }
        div.stElementContainer:has(.tesph-topbar), .tesph-topbar { pointer-events:none; }
        .tesph-topbar { position:fixed; inset:0 0 auto 0; z-index:100; display:grid; grid-template-columns:19.5rem minmax(0, 1fr) auto; align-items:stretch; width:auto; height:4.5rem; min-height:4.5rem; margin:0; padding:0; overflow:hidden; }
        .topbar-brand { display:flex; align-items:center; gap:.65rem; min-width:0; padding:0 1.25rem; border-right:1px solid rgba(26,18,8,.18); }
        .topbar-brand img { width:2.25rem; height:2.25rem; flex:0 0 2.25rem; box-sizing:border-box; object-fit:contain; padding:.16rem; border:1px solid rgba(26,18,8,.20); border-radius:.38rem; background:#FFFFFF; }
        .topbar-brand-name { overflow:hidden; color:#1A1208; font-size:.875rem; font-weight:700; line-height:1.2; text-overflow:ellipsis; white-space:nowrap; }
        .topbar-brand-subtitle { color:#3D2810; font-size:.6875rem; line-height:1.25; }
        .topbar-page { display:flex; flex-direction:column; justify-content:center; min-width:0; padding:0 1.5rem; }
        .topbar-right { min-width:0; padding:0 1.5rem 0 .75rem; gap:.45rem; }
        .topbar-admin { display:inline-flex; align-items:center; gap:.42rem; height:2.25rem; box-sizing:border-box; padding:.28rem .48rem; border:1px solid rgba(26,18,8,.15); border-radius:.35rem; background:rgba(255,255,255,.62); color:#1A1208; font-size:.75rem; font-weight:600; line-height:1; }
        .topbar-admin-icon { display:grid; place-items:center; width:1.1rem; height:1.1rem; border-radius:50%; background:#DEDCD7; color:#3D3832; }
        .topbar-admin-icon svg { width:.78rem; height:.78rem; fill:currentColor; }
        .topbar-admin-caret { width:0; height:0; margin-left:.08rem; border-top:4px solid #514B43; border-right:3px solid transparent; border-left:3px solid transparent; }
        .topbar-account-divider { height:1.25rem; margin:0 .08rem; }
        .topbar-logout-slot { width:5.05rem; height:2.25rem; flex:0 0 5.05rem; }
        div.st-key-topbar_logout { position:fixed; top:1.15rem; right:1.5rem; z-index:101; width:auto !important; }
        div.st-key-topbar_logout button { display:inline-flex !important; align-items:center !important; gap:.35rem !important; min-height:2.25rem !important; padding:.35rem .6rem !important; border:1px solid rgba(26,18,8,.15) !important; border-radius:.35rem !important; background:#FFFDF8 !important; color:#785615 !important; font-size:.75rem !important; font-weight:600 !important; line-height:1 !important; box-shadow:none !important; }
        div.st-key-topbar_logout button::before { content:"↪"; color:#A87512; font-size:1rem; line-height:1; }
        div.st-key-topbar_logout button:hover { background:#FFFAE8 !important; border-color:rgba(26,18,8,.24) !important; }
        @media (max-width:900px) {
          section[data-testid="stSidebar"] { top:4.5rem !important; height:calc(100vh - 4.5rem) !important; }
          .tesph-topbar { grid-template-columns:minmax(11.5rem, auto) minmax(0, 1fr) auto; margin:0; padding:0; }
          .topbar-brand { padding:0 .9rem; }
          .topbar-page { padding:0 .85rem; }
          .topbar-right { padding:0 .75rem 0 .25rem; }
          div.st-key-topbar_logout { right:.75rem; }
        }
        @media (max-width:600px) {
          .tesph-topbar { grid-template-columns:minmax(0, 1fr) auto; }
          .topbar-brand, .topbar-right > :not(.topbar-logout-slot) { display:none; }
          .topbar-page { padding:0 .5rem 0 3rem; }
          .topbar-title { font-size:.9rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          .topbar-breadcrumb { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        .section-title { margin:1.65rem 0 .25rem; color:#1F1F1F; font-size:1.04rem; font-weight:700; }
        .section-description { margin:0 0 .9rem; color:#6B6259; font-size:.82rem; line-height:1.45; }
        .processing-panel,.success-panel,.validation-panel { margin:.9rem 0; padding:1rem 1.1rem; border-radius:.5rem; }
        .processing-panel { border:1px solid #E8D9A8; background:#FFFAE8; }
        .success-panel { border:1px solid #C8E0D0; background:#EDF7F0; }
        .validation-panel { border:1px solid #E9C8BF; background:#FFF6F3; }
        .state-title { margin:0 0 .24rem; color:#1F1F1F; font-size:.93rem; font-weight:700; }
        .state-copy { margin:0; color:#6B6259; font-size:.8rem; line-height:1.45; }
        .validation-list { margin:.7rem 0 0 1.15rem; padding:0; color:#6B6259; font-size:.8rem; line-height:1.55; }
        .success-metric { margin-top:.7rem; color:#3D7A53; font-size:.78rem; font-weight:600; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hide_sidebar_for_logged_out_user() -> None:
    """Hide Streamlit's otherwise-empty native sidebar before authentication."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] { display:none !important; }
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


def render_sidebar() -> None:
    """Render the approved navigation below the application-wide top bar."""
    groups = (("Overview", (("pages/dashboard.py", "Dashboard", ":material/dashboard:"),)), ("Data", (("pages/data_upload.py", "Data Upload & ETL", ":material/upload_file:"),)), ("Analyze", (("pages/sales_product_analytics.py", "Sales & Product Analytics", ":material/analytics:"), ("pages/demand_forecast.py", "Demand Forecast", ":material/trending_up:"), ("pages/stock_out_risk.py", "Stock-Out Risk", ":material/warning:"))), ("Decide", (("pages/replenishment_recommendations.py", "Replenishment Recommendations", ":material/refresh:"), ("pages/product_prioritization.py", "Product Prioritization", ":material/format_list_numbered:"))))
    with st.sidebar:
        for section, links in groups:
            st.markdown(f'<div class="nav-section">{section}</div>', unsafe_allow_html=True)
            for target, label, icon in links:
                st.page_link(target, label=label, icon=icon, use_container_width=True)
        if get_data_status() is not DataStatus.DATA_READY:
            st.markdown('<div class="nav-gate-note">Analytics and decision pages require a processed dataset. They remain available for review.</div>', unsafe_allow_html=True)


def render_login_screen() -> None:
    """Render the local authorized-user login screen."""
    st.markdown('<div class="login-spacer"></div>', unsafe_allow_html=True)
    left, content, right = st.columns((1.2, 1, 1.2))
    with content:
        st.markdown(
            f'<div class="login-brand"><img src="{_logo_data_uri()}" alt="TheEverythingShopPH logo">'
            '<h1 class="login-title">TheEverythingShopPH</h1>'
            '<p class="login-subtitle">Decision Support System</p></div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            st.markdown('<span class="login-form-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
            with st.form("prototype_login_form"):
                username = st.text_input("Username", placeholder="Enter your username")
                password = st.text_input("Password", type="password", placeholder="Enter your password")
                submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
            if submitted:
                if not is_authentication_configured():
                    st.error("Local authorized-user access is not configured. Add the local auth configuration and restart the app.")
                elif authenticate(username.strip(), password):
                    start_authenticated_session()
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        st.markdown(
            '<p class="login-note">Internal decision-support tool · Does not place orders or modify Shopee inventory.</p>',
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


def render_page_shell(title: str, breadcrumb: str) -> None:
    """Render the Figma-inspired topbar consistently on every approved page."""
    st.markdown(
        f'<div class="tesph-topbar-spacer" aria-hidden="true"></div>'
        f'<header class="tesph-topbar">'
        f'<div class="topbar-brand"><img src="{_logo_data_uri()}" alt="TheEverythingShopPH logo"><div><div class="topbar-brand-name">TheEverythingShopPH</div><div class="topbar-brand-subtitle">Decision Support</div></div></div>'
        f'<div class="topbar-page"><div class="topbar-breadcrumb">{breadcrumb}</div><div class="topbar-title">{title}</div></div>'
        f'<div class="topbar-right">{data_status_indicator()}<div class="topbar-divider"></div><div class="topbar-admin" aria-label="Admin"><span class="topbar-admin-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4.42 0-8 2.01-8 4.5V20h16v-1.5c0-2.49-3.58-4.5-8-4.5Z"/></svg></span><span>Admin</span><span class="topbar-admin-caret" aria-hidden="true"></span></div><div class="topbar-divider topbar-account-divider"></div><div class="topbar-logout-slot" aria-hidden="true"></div></div>'
        f'</header>',
        unsafe_allow_html=True,
    )
    st.button("Log out", key="topbar_logout", on_click=logout)


def card_header(title: str, subtitle: str | None = None, right_text: str | None = None) -> None:
    """Render a shared card heading and divider."""
    subtitle_html = f'<p class="card-subtitle">{subtitle}</p>' if subtitle else ""
    right = f'<span class="card-subtitle">{right_text}</span>' if right_text else ""
    st.markdown(f'<div class="card-header"><div><h3 class="card-title">{title}</h3>{subtitle_html}</div>{right}</div>', unsafe_allow_html=True)


def section_header(title: str, description: str | None = None) -> None:
    """Render a page section without unnecessarily boxing the content."""
    description_html = f'<p class="section-description">{description}</p>' if description else ""
    st.markdown(f'<h2 class="section-title">{title}</h2>{description_html}', unsafe_allow_html=True)


def kpi_card(label: str, value: str | None = None, accent: bool = False) -> None:
    """Render a KPI or a no-data skeleton without fabricated values."""
    marker = '<span style="display:inline-block;width:4px;height:14px;margin-right:8px;border-radius:3px;background:#EEAC17;vertical-align:-2px"></span>' if accent else ""
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


def render_upload_summary(file_name: str) -> None:
    suffix = Path(file_name).suffix.upper().lstrip(".") or "FILE"
    st.markdown(f'<div class="upload-summary"><div class="file-icon">▤</div><div><div class="file-name">{file_name}</div><div class="file-meta">{suffix} selected · Pending ETL validation · No rows have been read</div></div></div>', unsafe_allow_html=True)


def schema_placeholder() -> None:
    st.markdown('<div class="schema-placeholder"><div class="schema-icon">▦</div><p class="schema-title">Schema mapping pending</p><p class="schema-copy">The ETL module will validate source columns and report an explicit mapping after processing. No source fields are assumed here.</p></div>', unsafe_allow_html=True)


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
