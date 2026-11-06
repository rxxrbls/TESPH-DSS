"""Stock-out risk dashboard."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from utils.components import (
    empty_state,
    guard_protected_page,
    info_message,
    render_page_shell,
    section_header,
)
from utils.state import (
    DataStatus,
    ensure_derived_outputs_for_active_dataset,
    get_analytics_results,
    get_data_status,
    get_mca_results,
    get_prescriptive_error_message,
    get_risk_results,
)


RISK_FILTER_KEY = "stock_out_risk_filter"
PRODUCT_SELECT_KEY = "stock_out_risk_product"
DISPLAY_COLUMNS = [
    "Product",
    "Current Stock",
    "Forecast Demand",
    "Movement",
    "Sales Velocity (units/day)",
    "Stock-Out Risk",
    "Priority",
]
RISK_COLORS = {
    "Critical": "#8F3329",
    "High": "#B84F3F",
    "Medium": "#C99416",
    "Low": "#3D7A53",
    "No Forecast Demand": "#81786D",
}


def _frame(value: object) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _inject_stock_risk_styles() -> None:
    st.markdown(
        """
        <style>
        .risk-card {
            min-height:5.4rem;
            margin-bottom:.55rem;
            padding:.7rem .85rem;
            border:1px solid var(--tesph-border);
            border-radius:var(--tesph-radius);
            background:var(--tesph-surface);
            box-shadow:var(--tesph-shadow);
            display:flex;
            flex-direction:column;
            align-items:center;
            justify-content:center;
            text-align:center;
        }
        .risk-card-title {
            margin:0 0 .22rem;
            color:var(--tesph-text-muted);
            font-size:.7rem;
            font-weight:700;
        }
        .risk-card-value {
            margin:0;
            color:var(--tesph-text);
            font-size:1.55rem;
            line-height:1;
            font-weight:750;
        }
        .risk-card-note {
            display:block;
            margin:.22rem 0 0;
            color:var(--tesph-text-subtle);
            font-size:.68rem;
            line-height:1.2;
        }
        .risk-summary-classification {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:.5rem;
            padding:.15rem .1rem;
            color:var(--tesph-text-muted);
            font-size:.78rem;
        }
        .risk-summary-classification strong {
            color:var(--tesph-text);
            font-weight:750;
            text-align:right;
        }
        .st-key-stock_out_risk_product {
            padding-top:1.65rem;
        }
        .st-key-stock_forecast_panel {
            margin-top:.1rem;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox > [role="group"] {
            border:1.5px solid #D9980F !important;
            border-radius:var(--tesph-radius) !important;
            background:#D9980F !important;
            background-color:#FFFFFF !important;
            color:#22201D !important;
            box-shadow:none !important;
            outline:none !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox input {
            background:transparent !important;
            background-color:transparent !important;
            color:#22201D !important;
            caret-color:#22201D !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox button {
            border:0 !important;
            background:transparent !important;
            background-color:transparent !important;
            color:#22201D !important;
            box-shadow:none !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox button svg {
            color:#22201D !important;
            fill:#22201D !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox > [role="group"]:hover {
            border-color:#B77908 !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox > [role="group"]:focus-within {
            border-color:#B77908 !important;
            background:#D9980F !important;
            background-color:#FFFFFF !important;
            box-shadow:0 0 0 3px rgba(217, 152, 15, 0.24) !important;
            outline:none !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox input:focus,
        .st-key-stock_out_risk_product .react-aria-ComboBox *:focus {
            outline:none !important;
            box-shadow:none !important;
        }
        .st-key-stock_out_risk_product .react-aria-ComboBox span {
            color:#22201D !important;
        }
        .st-key-stock_out_risk_product * {
            caret-color:#D9980F !important;
        }
        .risk-overview-kpi {
            display:flex;
            min-height:6.45rem;
            height:100%;
            flex-direction:column;
            align-items:center;
            justify-content:center;
            padding:1rem 1.05rem;
            border:1px solid var(--tesph-border);
            border-radius:var(--tesph-radius);
            background:var(--tesph-surface);
            box-shadow:var(--tesph-shadow);
            text-align:center;
        }
        .risk-overview-kpi-label {
            color:var(--tesph-text-subtle);
            font-size:.68rem;
            font-weight:700;
            letter-spacing:.04em;
            text-transform:uppercase;
        }
        .risk-overview-kpi-value {
            margin-top:.45rem;
            color:var(--tesph-text);
            font-size:clamp(1.25rem, 1.8vw, 1.58rem);
            font-weight:700;
            line-height:1.18;
        }
        .risk-distribution-title {
            margin-top: 2.0rem !important;
            color:var(--tesph-text-subtle);
            font-size:.68rem;
            font-weight:700;
            letter-spacing:.04em;
            text-align:left;
            text-transform:uppercase;
        }
        .st-key-risk_distribution_chart {
            margin-top:4px !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.risk-overview-marker)
        div[data-testid="stVerticalBlockBorderWrapper"] {
            height:100% !important;
        }
        .risk-filter-row {
            display:flex;
            justify-content:flex-end;
            gap:.45rem;
            margin:0;
        }
        .st-key-risk_filter_controls {
            margin-bottom:-.8rem;
        }
        .risk-filter-row div[data-testid="stButton"] > button {
            min-height:2rem !important;
            padding:.2rem .8rem !important;
            border-radius:999px !important;
            border:1px solid var(--tesph-border) !important;
            box-shadow:none !important;
            font-size:.76rem !important;
            font-weight:750 !important;
        }
        .risk-filter-row div[data-testid="stButton"] > button[kind="primary"] {
            border-color:#D9980F !important;
            background:#D9980F !important;
            color:#22201D !important;
        }
        .risk-filter-row div[data-testid="stButton"] > button[kind="secondary"] {
            background:#FFFFFF !important;
            color:#22201D !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _number(value: object, decimals: int = 0) -> str:
    if pd.isna(value):
        return "Unavailable"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals == 0:
        return f"{numeric:,.0f}"
    return f"{numeric:,.{decimals}f}"


def _dedup(frame: pd.DataFrame, keys: list[str], columns: list[str]) -> pd.DataFrame:
    available = [column for column in columns if column in frame.columns]
    if not set(keys).issubset(frame.columns) or not available:
        return pd.DataFrame(columns=keys + available)
    return frame[keys + available].dropna(subset=keys, how="all").drop_duplicates(keys)


def _risk_base(
    risk: pd.DataFrame,
    analytics: dict[str, pd.DataFrame] | None,
    mca: pd.DataFrame,
) -> pd.DataFrame:
    base = risk.copy()
    analytics = analytics or {}
    for column in ("SKU", "Product", "Current Stock", "Forecast Demand", "Stock-Out Risk"):
        if column not in base:
            base[column] = pd.NA

    movement = _dedup(
        _frame(analytics.get("movement_classified")),
        ["SKU"],
        ["Movement Classification"],
    )
    if not movement.empty and "SKU" in base:
        base = base.merge(movement, on="SKU", how="left")

    if "Movement Classification" not in base:
        base["Movement Classification"] = pd.NA

    if "Sales Velocity" not in base:
        mca_velocity = _dedup(mca, ["SKU"], ["Sales Velocity"])
        if not mca_velocity.empty and "SKU" in base:
            base = base.merge(mca_velocity, on="SKU", how="left")

    priority = _dedup(mca, ["SKU"], ["Priority Level"])
    if not priority.empty and "SKU" in base:
        base = base.merge(priority, on="SKU", how="left")

    for column in ("Movement Classification", "Sales Velocity", "Priority Level"):
        if column not in base:
            base[column] = pd.NA
    return base


def _display_table(base: pd.DataFrame) -> pd.DataFrame:
    display = pd.DataFrame(
        {
            "Product": base.get("Product", pd.Series(dtype="object")),
            "Current Stock": base.get("Current Stock", pd.Series(dtype="float")),
            "Forecast Demand": base.get("Forecast Demand", pd.Series(dtype="float")),
            "Movement": base.get("Movement Classification", pd.Series(dtype="object")),
            "Sales Velocity (units/day)": base.get("Sales Velocity", pd.Series(dtype="float")),
            "Stock-Out Risk": base.get("Stock-Out Risk", pd.Series(dtype="object")),
            "Priority": base.get("Priority Level", pd.Series(dtype="object")),
        }
    )
    return display.fillna("Unavailable")[DISPLAY_COLUMNS]


def _render_kpi(title: str, value: object, note: str) -> None:
    display_value = f"{value:,}" if isinstance(value, int) else str(value)
    note_html = (
        f'<p class="risk-card-note">{html.escape(note)}</p>'
        if note
        else ""
    )
    st.markdown(
        f"""
        <div class="risk-card">
            <p class="risk-card-title">{html.escape(title)}</p>
            <p class="risk-card-value">{html.escape(display_value)}</p>
            {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_overview_kpi(title: str, value: int) -> None:
    st.markdown(
        f"""
        <div class="risk-overview-kpi">
            <div class="risk-overview-kpi-label">{html.escape(title)}</div>
            <div class="risk-overview-kpi-value">{value:,}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_distribution(counts: pd.Series) -> None:
    order = ["High", "Medium", "Low"]
    data = pd.DataFrame(
        {
            "Risk": order,
            "Products": [int(counts.get(level, 0)) for level in order],
            "Color": [RISK_COLORS[level] for level in order],
        }
    )
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 4},
        "encoding": {
            "y": {
                "field": "Risk",
                "type": "nominal",
                "sort": order,
                "title": None,
                "axis": {"labelColor": "#625C54"},
            },
            "x": {
                "field": "Products",
                "type": "quantitative",
                "title": None,
                "axis": {
                    "grid": True,
                    "gridColor": "#EAE5DC",
                    "gridOpacity": 1,
                    "labelColor": "#625C54",
                    "tickMinStep": 1,
                },
            },
            "color": {
                "field": "Risk",
                "type": "nominal",
                "scale": {"domain": order, "range": data["Color"].tolist()},
                "legend": None,
            },
            "tooltip": [
                {"field": "Risk", "type": "nominal"},
                {"field": "Products", "type": "quantitative", "format": ","},
            ],
        },
        "height": 135,
        "config": {
            "view": {"stroke": None},
            "axis": {"gridWidth": 1},
        },
    }
    st.vega_lite_chart(data, chart, use_container_width=True)


def _risk_filter() -> str:
    with st.container(key="risk_filter_controls"):
        st.markdown('<div class="risk-filter-row">', unsafe_allow_html=True)
        columns = st.columns(4, gap="small")
        current = st.session_state.get(RISK_FILTER_KEY, "All")
        for index, label in enumerate(("All", "High", "Medium", "Low")):
            with columns[index]:
                if st.button(
                    label,
                    key=f"risk_filter_{label.lower()}",
                    type="primary" if current == label else "secondary",
                    use_container_width=True,
                ):
                    st.session_state[RISK_FILTER_KEY] = label
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    return st.session_state.get(RISK_FILTER_KEY, "All")


def _selected_product(base: pd.DataFrame) -> pd.Series | None:
    options = (
        base.assign(_label=base["Product"].astype(str) + " (" + base["SKU"].astype(str) + ")")
        .sort_values(["Product", "SKU"], kind="stable")
        .reset_index(drop=True)
    )
    if options.empty:
        return None
    labels = options["_label"].tolist()
    if st.session_state.get(PRODUCT_SELECT_KEY) not in labels:
        st.session_state[PRODUCT_SELECT_KEY] = labels[0]
    selected = st.selectbox(
        "Select product",
        labels,
        key=PRODUCT_SELECT_KEY,
        label_visibility="collapsed",
    )
    selected_options = options.loc[options["_label"].eq(selected)]
    if selected_options.empty:
        return options.iloc[0]
    return selected_options.iloc[0]


def _render_stock_vs_demand(row: pd.Series) -> None:
    stock = pd.to_numeric(row.get("Current Stock"), errors="coerce")
    demand = pd.to_numeric(row.get("Forecast Demand"), errors="coerce")
    chart_data = pd.DataFrame(
        {
            "Measure": ["Current Stock", "Forecast Demand"],
            "Units": [stock if pd.notna(stock) else 0, demand if pd.notna(demand) else 0],
            "Color": ["#C8AE72", "#D9980F"],
        }
    )
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 5, "size": 28},
        "encoding": {
            "y": {
                "field": "Measure",
                "type": "nominal",
                "sort": None,
                "title": None,
                "axis": {"labelPadding": 8, "labelLimit": 150, "labelColor": "#625C54"},
            },
            "x": {
                "field": "Units",
                "type": "quantitative",
                "title": "Units",
                "axis": {
                    "grid": True,
                    "gridColor": "#EAE5DC",
                    "gridOpacity": 1,
                    "labelColor": "#625C54",
                    "titleColor": "#625C54",
                    "tickMinStep": 1,
                },
            },
            "color": {
                "field": "Measure",
                "type": "nominal",
                "scale": {
                    "domain": ["Current Stock", "Forecast Demand"],
                    "range": ["#C8AE72", "#D9980F"],
                },
                "legend": None,
            },
            "tooltip": [
                {"field": "Measure", "type": "nominal"},
                {"field": "Units", "type": "quantitative", "format": ",.0f"},
            ],
        },
        "height": 195,
        "padding": {"left": 4, "right": 8, "top": 8, "bottom": 4},
        "config": {
            "view": {"stroke": None},
            "axis": {"domain": False, "gridWidth": 1},
        },
    }

    left, right = st.columns((7, 3), gap="medium", vertical_alignment="top")
    with left:
        st.vega_lite_chart(chart_data, chart, use_container_width=True)
    with right:
        _render_kpi("Current Stock", _number(stock), "")
        _render_kpi(
            "Forecast Demand",
            _number(demand),
            "",
        )
        st.markdown(
            f'<div class="risk-summary-classification"><span>Stock-Out Risk</span><strong>{html.escape(str(row.get("Stock-Out Risk", "Unavailable")))}</strong></div>',
            unsafe_allow_html=True,
        )


guard_protected_page()
ensure_derived_outputs_for_active_dataset(include_analytics=False)
render_page_shell("Stock-Out Risk", "Analyze · Predictive")
_inject_stock_risk_styles()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing stock-out risk inputs.")
    st.stop()

risk_output = get_risk_results()
if risk_output is None or risk_output.empty:
    error_message = get_prescriptive_error_message()
    if error_message:
        info_message(error_message)
    else:
        info_message("Current-stock risk is not available for the active dataset.")
    st.stop()

analytics_results = get_analytics_results()
mca_results = _frame(get_mca_results())
base = _risk_base(risk_output, analytics_results, mca_results)
distinct_base = base.drop_duplicates(subset=["SKU"]) if "SKU" in base else base.copy()
risk_counts = distinct_base["Stock-Out Risk"].value_counts(dropna=False)
overview_content_column, distribution_column = st.columns(
    (1.45, 1),
    gap="medium",
    vertical_alignment="top",
)
with overview_content_column:
    section_header(
        "Risk Overview",
        "View the distribution of stock-out risk levels across products based on current inventory and forecasted demand.",
    )
    st.markdown('<span class="risk-overview-marker"></span>', unsafe_allow_html=True)
    overview_columns = st.columns(3, gap="medium", vertical_alignment="top")
    with overview_columns[0]:
        _render_overview_kpi("High Risk", int(risk_counts.get("High", 0)))
    with overview_columns[1]:
        _render_overview_kpi("Medium Risk", int(risk_counts.get("Medium", 0)))
    with overview_columns[2]:
        _render_overview_kpi("Low Risk", int(risk_counts.get("Low", 0)))

with distribution_column:
    st.markdown(
        '<p class="risk-distribution-title">Risk Distribution</p>',
        unsafe_allow_html=True,
    )
    with st.container(key="risk_distribution_chart"):
        _render_distribution(risk_counts)

header_left, header_right = st.columns((1, .85), gap="large", vertical_alignment="bottom")
with header_left:
    section_header(
        "Stock-Out Risk by Product",
        "Review product-level stock availability, forecasted demand, and stock-out risk classifications.",
    )
with header_right:
    selected_filter = _risk_filter()

filtered = base.copy()
if selected_filter in {"High", "Medium", "Low"}:
    filtered = filtered.loc[filtered["Stock-Out Risk"].astype(str).eq(selected_filter)]

display = _display_table(filtered)
st.dataframe(
    display,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Current Stock": st.column_config.NumberColumn("Current Stock", format="%.0f"),
        "Forecast Demand": st.column_config.NumberColumn("Forecast Demand", format="%.0f"),
        "Sales Velocity (units/day)": st.column_config.NumberColumn("Sales Velocity (units/day)", format="%.2f"),
    },
)

comparison_title, comparison_select = st.columns(
    (1, .65),
    gap="large",
    vertical_alignment="top",
)
with comparison_title:
    section_header(
        "Current Stock vs Forecast Demand",
        "Compare available inventory against forecasted demand for the selected product.",
    )
with comparison_select:
    selected_row = _selected_product(base)

with st.container(border=True, key="stock_forecast_panel"):
    if selected_row is not None:
        _render_stock_vs_demand(selected_row)
