"""Help and user guide page for the TESPH DSS."""

from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st

from utils.components import guard_protected_page, render_page_shell
from utils.icons import icon_svg


GUIDES = [
    {
        "title": "Getting Started",
        "description": "An overview of TheEverythingShopPH and how to begin using the system.",
        "body": "Start by signing in, checking the data status, uploading the latest Shopee and stock files, then reviewing the generated analytics and recommendations.",
        "steps": [
            ("Sign in to your account", "Use your authorized credentials to access the system."),
            ("Check Data ready", "Use the top bar status to confirm whether a processed dataset is already available."),
            ("Upload and process data", "Open Data Upload & ETL when the system needs a fresh Shopee transaction export or stock file."),
            ("Review decision pages", "Use the dashboard, analytics, forecasts, risk view, prioritization, and recommendations to support inventory decisions."),
        ],
    },
    {
        "title": "Data Upload & ETL",
        "description": "Prepare Shopee transaction and stock data for all DSS pages.",
        "body": "This page accepts supported Shopee transaction exports, validates the detected columns, runs the ETL steps, and publishes clean data for the rest of the app. It also includes a current stock upload area and a stock-out threshold input.",
        "steps": [
            ("Choose the Shopee export", "Use the file uploader to select the latest transaction export."),
            ("Review detected schema", "Check the detected columns and validation output before relying on the dataset."),
            ("Run the ETL flow", "Process only validated files so dashboards and models use clean transaction data."),
            ("Upload stock data when needed", "Use the stock upload section so risk and replenishment pages can compare demand against current stock."),
        ],
    },
    {
        "title": "Sales & Product Analytics",
        "description": "Understand sales, products, categories, returns, cancellations, and product movement.",
        "body": "This page summarizes the active processed transaction dataset with KPI cards, product performance tables, trend charts, return and cancellation views, and movement classifications.",
        "steps": [
            ("Start with the sales summary", "Use the KPI cards for a quick view of total sales and transaction activity."),
            ("Review product performance", "Check which products contribute the most revenue and quantity."),
            ("Inspect trends", "Use the monthly and category visuals to spot changes over time."),
            ("Check movement flags", "Use product movement outputs to identify products that may need business attention."),
        ],
    },
    {
        "title": "Demand Forecasting",
        "description": "Inspect demand forecasts generated from the current transaction history.",
        "body": "The forecasting page lets you review SKU and category demand projections. It includes method selection cards, category controls, charts, and detailed forecast tables when enough processed data is available.",
        "steps": [
            ("Select a forecast method", "Use the method buttons to compare the available forecasting output."),
            ("Choose the category or product view", "Use the available selector to focus the forecast on the items you want to inspect."),
            ("Read the chart", "Use the line or bar visuals to compare historical demand and projected demand."),
            ("Check the table", "Use the detailed rows when you need exact values for planning."),
        ],
    },
    {
        "title": "Stock-Out Risk",
        "description": "Identify products that may run out based on demand, forecast outputs, and current stock.",
        "body": "This page combines mapped stock data, demand signals, and forecast results to classify stock-out risk. It includes summary cards, risk distribution charts, detailed tables, and comparison controls.",
        "steps": [
            ("Review the risk summary", "Start with the overview cards to understand the number of items needing attention."),
            ("Use the risk table", "Sort or scan products by risk level, stock, and supporting metrics."),
            ("Inspect distribution charts", "Use the visuals to see how risk is spread across products or groups."),
            ("Compare selected items", "Use the selector controls to inspect specific products in more detail."),
        ],
    },
    {
        "title": "Product Prioritization (MCA)",
        "description": "Rank products using the approved multi-criteria analysis output.",
        "body": "Product Prioritization shows normalized MCA ranking results for products in the active dataset. The page includes a product selector, ranking table, and visual breakdowns for understanding priority scores.",
        "steps": [
            ("Open the ranking view", "Use the priority list to see which products are ranked highest."),
            ("Select a product", "Use the product selector to inspect one item more closely."),
            ("Read the score breakdown", "Use the chart and table outputs to understand why the product ranks where it does."),
            ("Use rankings as decision support", "Treat the ranking as guidance alongside stock, demand, and business judgment."),
        ],
    },
    {
        "title": "Replenishment Recommendations",
        "description": "Review suggested replenishment actions from stock position and demand signals.",
        "body": "This page presents replenishment guidance generated from the active stock, demand forecast, and recommendation rules. It includes summary cards and a recommendation table for planning restocks.",
        "steps": [
            ("Check recommendation totals", "Use the KPI cards to see the overall replenishment picture."),
            ("Review the table", "Scan the recommendations by product and suggested action."),
            ("Prioritize urgent items", "Use risk and recommendation fields to decide what needs attention first."),
            ("Validate before ordering", "Confirm supplier availability, budget, and business context before acting."),
        ],
    },
    {
        "title": "Dashboard",
        "description": "Get a high-level overview of the current processed dataset.",
        "body": "The Dashboard shows store overview KPIs, sales trends, category mix, top products, and recommendation highlights after data has been processed.",
        "steps": [
            ("Confirm data is ready", "The dashboard shows meaningful results only after a dataset has been processed."),
            ("Scan KPI cards", "Use the top cards for a quick status check."),
            ("Review charts and highlights", "Use trend, category, product, and recommendation sections to decide where to investigate next."),
        ],
    },
    {
        "title": "Account Settings",
        "description": "Manage profile, session, inventory reference, and system information.",
        "body": "Settings contains General, Inventory & Data, and System Information tabs. From there you can edit profile information, change password, adjust session timeout, open Help, and navigate to data upload tools.",
        "steps": [
            ("Use General settings", "Edit profile details, change password, or adjust session timeout where available."),
            ("Use Inventory & Data", "Review supported data formats and open the upload workflow."),
            ("Check System Information", "Use the system tab for local app and configuration details."),
        ],
    },
]


def _asset_uri(path: Path) -> str | None:
    if not path.is_file():
        return None
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _styles() -> None:
    st.markdown(
        """
        <style>
        .help-header { display:flex; align-items:flex-start; gap:1rem; margin:0 0 .9rem; }
        .help-header-icon { display:grid; margin-top:1rem; place-items:center; width:2.4rem; height:2.4rem; flex:0 0 2.4rem; border-radius:.55rem; background:#FEF7E7; color:#D9980F; }
        .help-header .section-title { margin:0 0 -.50rem !important; font-size:1.55rem !important; font-weight:700 !important; line-height:1.25 !important; }
        .help-header .section-description { margin:0 !important; }
        .guide-nav-card { display:none; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.guide-nav-panel-marker) {
            border:1px solid #E4DDD2 !important;
            border-radius:.55rem !important;
            background:#FFFDF8 !important;
            box-shadow:var(--tesph-shadow) !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.guide-nav-panel-marker) > div {
            padding:.8rem !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.guide-nav-panel-marker) [data-testid="stElementContainer"]:has(.guide-nav-panel-marker) {
            display:none !important;
            height:0 !important;
            min-height:0 !important;
            margin:0 !important;
            padding:0 !important;
            overflow:hidden !important;
        }
        [data-testid="column"]:has(.guide-nav-anchor) {
            min-height:34rem !important;
            padding:.72rem .72rem .15rem !important;
            border:1px solid #E4DDD2 !important;
            border-radius:.45rem !important;
            background:#FFFDF8 !important;
        }
        [data-testid="column"]:has(.guide-nav-anchor) div.stButton { margin:0 0 .05rem !important; }
        [data-testid="column"]:has(.guide-nav-anchor) div.stButton > button {
            justify-content:center !important;
            min-height:3.05rem !important;
            margin:0 !important;
            padding:.45rem .7rem !important;
            border:1px solid #E6DED2 !important;
            border-left-width:3px !important;
            border-left-color:transparent !important;
            border-radius:.42rem !important;
            background:#FFFFFF !important;
            color:#3D3832 !important;
            font-size:.78rem !important;
            font-weight:500 !important;
            line-height:1.2 !important;
            text-align:center !important;
            box-shadow:none !important;
        }
        [data-testid="column"]:has(.guide-nav-anchor) div.stButton > button p {
            width:100%;
            margin:0 !important;
            text-align:center !important;
        }
        [data-testid="column"]:has(.guide-nav-anchor) div.stButton > button:hover { border-color:#D9980F !important; background:#FFF9EA !important; color:#252525 !important; }
        .guide-content h2 { margin:.25rem 0 .6rem !important; color:#252525 !important; font-size:1.9rem !important; font-weight:850 !important; line-height:1.15 !important; }
        .guide-description { margin:0 0 1.15rem !important; color:#625C54 !important; font-size:.92rem !important; line-height:1.5 !important; }
        .guide-welcome { display:grid; grid-template-columns:minmax(10rem, .82fr) minmax(0, 1.18fr); gap:1.4rem; align-items:center; min-height:13.2rem; padding:1.45rem 1.65rem; border:1px solid #F0DEC0; border-radius:.55rem; background:#FFF6E6; }
        .guide-illustration { display:grid; place-items:center; min-width:0; }
        .guide-illustration img { width:min(15rem, 100%); height:auto; object-fit:contain; }
        .welcome-kicker { margin:0 0 .15rem !important; color:#625C54 !important; font-size:.86rem !important; }
        .welcome-title { margin:0 0 .7rem !important; color:#D9980F !important; font-size:.95rem !important; font-weight:850 !important; }
        .welcome-copy { margin:0 !important; color:#4D4943 !important; font-size:.9rem !important; line-height:1.65 !important; }
        .guide-info-card { padding:1.2rem 1.35rem; border:1px solid #F0DEC0; border-radius:.55rem; background:#FFF6E6; color:#4D4943; font-size:.92rem; line-height:1.65; }
        .guide-steps-title { margin:1.45rem 0 1rem !important; color:#252525 !important; font-size:.9rem !important; font-weight:850 !important; }
        .guide-step { display:grid; grid-template-columns:1.45rem minmax(0, 1fr); gap:.9rem; align-items:start; margin:0 0 1.05rem; padding-left:1.2rem; }
        .guide-step-number { display:grid; place-items:center; width:1.35rem; height:1.35rem; border:1px solid #D9980F; border-radius:999px; color:#D9980F; font-size:.7rem; font-weight:800; line-height:1; }
        .guide-step-title { margin:0 !important; color:#252525 !important; font-size:.86rem !important; font-weight:850 !important; line-height:1.3 !important; }
        .guide-step-copy { margin:.22rem 0 0 !important; color:#625C54 !important; font-size:.76rem !important; line-height:1.4 !important; }
        @media (max-width: 860px) {
            .help-header { margin-bottom:.75rem; }
            .guide-welcome { grid-template-columns:1fr; padding:1.2rem; }
            .guide-step { padding-left:.2rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_steps(steps: list[tuple[str, str]]) -> str:
    return "".join(
        f"""
        <div class="guide-step">
          <div class="guide-step-number">{index}</div>
          <div>
            <p class="guide-step-title">{html.escape(title)}</p>
            <p class="guide-step-copy">{html.escape(copy)}</p>
          </div>
        </div>
        """
        for index, (title, copy) in enumerate(steps, start=1)
    )


def _select_help_topic(topic: str) -> None:
    st.session_state["selected_help_topic"] = topic


guard_protected_page()
render_page_shell("Help & User Guide", "Support")
_styles()

st.markdown(
    f"""
    <header class="help-header">
      <div class="help-header-icon">{icon_svg("book_open", size=20, color="#D9980F")}</div>
      <div>
        <h2 class="section-title">Help &amp; User Guide</h2>
        <p class="section-description">Learn how to use TheEverythingShopPH and understand its analytical features.</p>
      </div>
    </header>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("selected_help_topic", GUIDES[0]["title"])
active_title = st.session_state["selected_help_topic"]
active_index = next((index for index, guide in enumerate(GUIDES, start=1) if guide["title"] == active_title), 1)

st.markdown(
    f"""
    <style>
    div.st-key-guide_topic_{active_index} button {{
        border-color:#E6DED2 !important;
        border-left-color:#E4DDD2 !important;
        background:#FFFFFF !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

nav_col, content_col = st.columns((0.31, 0.69), gap="large", vertical_alignment="top")

with nav_col:
    st.markdown('<span class="guide-nav-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<span class="guide-nav-panel-marker" aria-hidden="true"></span>', unsafe_allow_html=True)
        for index, guide in enumerate(GUIDES, start=1):
            topic = guide["title"]
            st.button(
                f"{index}. {topic}",
                key=f"guide_topic_{index}",
                width="stretch",
                on_click=_select_help_topic,
                args=(topic,),
            )

selected = GUIDES[active_index - 1]
laptop_uri = _asset_uri(Path(__file__).resolve().parent.parent / "assets" / "laptop_illustration.png")
laptop_html = f'<img src="{laptop_uri}" alt="TESPH-DSS dashboard illustration">' if laptop_uri else ""

with content_col:
    title = html.escape(selected["title"])
    description = html.escape(selected["description"])
    body = html.escape(selected["body"])
    if selected["title"] == "Getting Started":
        content_card = f"""
        <section class="guide-welcome">
          <div class="guide-illustration">{laptop_html}</div>
          <div>
            <p class="welcome-kicker">Welcome to</p>
            <p class="welcome-title">TheEverythingShopPH</p>
            <p class="welcome-copy">A decision support system designed to help TheEverythingShopPH manage inventory, forecast demand, and generate replenishment recommendations based on Shopee transaction data and current stock data.</p>
          </div>
        </section>
        """
    else:
        content_card = f'<section class="guide-info-card">{body}</section>'

    st.markdown(
        f"""
        <article class="guide-content">
          <h2>{active_index}. {title}</h2>
          <p class="guide-description">{description}</p>
          {content_card}
          <p class="guide-steps-title">How to use this section:</p>
          {_render_steps(selected["steps"])}
        </article>
        """,
        unsafe_allow_html=True,
    )
