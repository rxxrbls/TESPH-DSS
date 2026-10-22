"""Descriptive sales and product analytics from the approved analytics pipeline."""

from html import escape

import pandas as pd
import streamlit as st

from utils.analytics_display import currency, number, percent, render_product_performance, render_sales_trend
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, primary_button, render_page_shell, section_header
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_error_message, get_analytics_results, get_data_status, get_recommendation_results, get_risk_results


def _movement_label(value: object) -> str:
    label = str(value or "").strip()
    return {
        "Fast Moving": "Fast",
        "Regular Moving": "Steady",
        "Slow Moving": "Slow",
        "No Movement": "No Movement",
    }.get(label, label or "Not available")


def _badge_class(value: object) -> str:
    label = str(value or "").strip().lower()
    if label in {"fast", "high", "critical"}:
        return "badge-warm"
    if label in {"steady", "regular moving", "medium"}:
        return "badge-gold"
    if label in {"slow", "low"}:
        return "badge-green"
    return "badge-muted"


def _first_existing(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _enrich_movement_table(movement: pd.DataFrame) -> pd.DataFrame:
    table = movement.copy()
    table["Movement"] = table["Movement Classification"].map(_movement_label)
    table["Units Sold"] = pd.to_numeric(
        table.get("Recent Demand", table.get("Gross Demand")),
        errors="coerce",
    )

    stock_source = get_recommendation_results()
    risk_source = get_risk_results()
    if stock_source is None or stock_source.empty:
        stock_source = risk_source

    if stock_source is not None and not stock_source.empty:
        lookup = stock_source.copy()
        join_key = None
        for candidate in ("Product Key", "SKU", "Product"):
            if candidate in table.columns and candidate in lookup.columns:
                join_key = candidate
                break
        if join_key:
            value_columns = [join_key]
            current_stock = _first_existing(lookup, ("Current Stock", "Stock", "current_stock"))
            risk_level = _first_existing(lookup, ("Stock-Out Risk", "stock_out_risk_level", "Risk Level"))
            if current_stock:
                value_columns.append(current_stock)
            if risk_level:
                value_columns.append(risk_level)
            lookup = lookup[value_columns].drop_duplicates(subset=[join_key])
            table = table.merge(lookup, on=join_key, how="left", suffixes=("", "_risk"))
            if current_stock and current_stock != "Current Stock":
                table = table.rename(columns={current_stock: "Current Stock"})
            if risk_level and risk_level != "Stock-Out Risk":
                table = table.rename(columns={risk_level: "Stock-Out Risk"})

    for column in ("Current Stock", "Stock-Out Risk"):
        if column not in table.columns:
            table[column] = pd.NA
    return table


def _render_product_movement_table(movement: pd.DataFrame, *, limit: int = 12) -> None:
    display = _enrich_movement_table(movement)
    movement_priority = {
        "Fast": 1,
        "Steady": 2,
        "Slow": 3,
        "No Movement": 4,
    }

    display["_movement_priority"] = (
        display["Movement"]
        .map(movement_priority)
        .fillna(5)
    )

    display = (
        display.sort_values(
            ["_movement_priority", "Units Sold", "Product"],
            ascending=[True, False, True],
            na_position="last",
        )
        .head(limit)
        .drop(columns="_movement_priority")
    )

    rows = []
    for _, row in display.iterrows():
        product = escape(str(row.get("Product", "Not available")))
        category = escape(str(row.get("Category", "Not available")))
        units = number(row.get("Units Sold"))
        stock = "Not available" if pd.isna(row.get("Current Stock")) else number(row.get("Current Stock"))
        movement_label = escape(str(row.get("Movement", "Not available")))
        risk_value = row.get("Stock-Out Risk")
        risk_label = "Not available" if pd.isna(risk_value) else escape(str(risk_value))
        rows.append(
            "<tr>"
            f"<td class='movement-product'>{product}</td>"
            f"<td>{category}</td>"
            f"<td class='numeric'>{units}</td>"
            f"<td class='numeric'>{stock}</td>"
            f"<td><span class='movement-badge {_badge_class(movement_label)}'>{movement_label}</span></td>"
            f"<td><span class='movement-badge {_badge_class(risk_label)}'>{risk_label}</span></td>"
            "</tr>"
        )

    st.markdown(
        """
        <style>
        .movement-table-wrap { border:1px solid #E4DDD2; border-radius:.45rem; overflow:hidden; background:#FFFFFF; }
        .movement-table { width:100%; border-collapse:collapse; font-size:.88rem; color:#3A3835; }
        .movement-table th { padding:.78rem 1.05rem; border-bottom:1px solid #E4DDD2; color:#8A8379; font-size:.72rem; font-weight:800; text-transform:uppercase; text-align:left; }
        .movement-table td { padding:.82rem 1.05rem; border-bottom:1px solid #EDE7DC; vertical-align:middle; }
        .movement-table tr:last-child td { border-bottom:0; }
        .movement-table .numeric { text-align:right; font-variant-numeric:tabular-nums; }
        .movement-product { color:#2E2C29; font-weight:400; }
        .movement-badge { display:inline-flex; align-items:center; justify-content:center; min-width:2.65rem; padding:.18rem .5rem; border-radius:.38rem; font-size:.72rem; font-weight:500; line-height:1.1; }
        .movement-badge.badge-warm { border:1px solid #E9C9AA; background:#F7DEC5; color:#805127; }
        .movement-badge.badge-gold { border:1px solid #E6D37E; background:#F8ECA8; color:#7A610B; }
        .movement-badge.badge-green { border:1px solid #BFDCCB; background:#E6F3EA; color:#3D7452; }
        .movement-badge.badge-muted { border:1px solid #DDD6CB; background:#F5F1EA; color:#6B6259; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='movement-table-wrap'><table class='movement-table'>"
        "<thead><tr><th>Product</th><th>Category</th><th>Units sold</th><th>Current stock</th><th>Movement</th><th>Stock-out risk</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


guard_protected_page()
render_page_shell("Sales & Product Analytics", "Analyze · Descriptive")
ensure_derived_outputs_for_active_dataset(include_forecast=False)

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available yet", "Upload and process a Shopee transaction file to view sales and product analytics.", "Data")
    if primary_button("Upload data", key="analytics_go_to_upload"):
        st.switch_page("pages/data_upload.py")
    st.stop()

analytics = get_analytics_results()
if not analytics or analytics.get("sales_summary") is None or analytics["sales_summary"].empty:
    empty_state("Analytics are not available", "The processed dataset is present, but descriptive analytics could not be prepared for this session.", "Data")
    if get_analytics_error_message():
        info_message(get_analytics_error_message())
    st.stop()

summary = analytics["sales_summary"].iloc[0]
section_header("Sales summary", "Real metrics from the current processed transaction dataset.")
summary_cards = (
    ("Gross revenue", currency(summary["Gross Revenue"]), False),
    ("Net revenue after returns", currency(summary["Net Revenue After Returns"]), False),
    ("Gross demand", number(summary["Gross Demand"]), False),
    ("Return quantity rate", percent(summary["Return Quantity Rate"]), False),
    ("Cancellation order rate", percent(summary["Cancellation Order Rate"]), False),
)
for column, (label, value, accent) in zip(st.columns(5, gap="small"), summary_cards, strict=True):
    with column:
        kpi_card(label, value, accent=accent)

section_header("Product performance", "Products are ranked by gross revenue; quantities and returns remain visible in the detail table.")
products = analytics.get("product_performance")
if not render_product_performance(products, height=340):
    info_message("Product performance data is unavailable for this processed dataset.")

section_header("Sales trends", "Monthly category trends using net revenue after returns.")
sales_trends = analytics.get("sales_trends")
if not render_sales_trend(sales_trends, height=340):
    info_message("Sales trend data is unavailable for this processed dataset.")

returns_column, cancellations_column = st.columns(2, gap="large")
with returns_column:
    section_header("Returns", "Return indicators from order and returned-quantity statuses.")
    returns = analytics.get("return_indicators")
    if returns is not None and not returns.empty:
        return_summary = returns.iloc[0]
        cols = st.columns(2)
        with cols[0]:
            kpi_card(
            "Returned quantity",
            number(return_summary["Returned Quantity"]),
        )
        with cols[1]:
            kpi_card("Return order rate", percent(return_summary["Return Order Rate"]))
    else:
        info_message("Return indicators are unavailable for this processed dataset.")

with cancellations_column:
    section_header("Cancellations", "Order-status indicators supplied by descriptive analytics.")
    status = analytics.get("order_status")
    cancellation_rows = pd.DataFrame()
    if status is not None and "Order Status" in status.columns:
        cancellation_rows = status.loc[status["Order Status"].astype("string").str.contains("cancel", case=False, na=False)]
    if cancellation_rows.empty:
        info_message("No cancelled orders were recorded in the processed dataset.")
    else:
        cancellation = cancellation_rows.iloc[0]
        cols = st.columns(2)
        with cols[0]:
            kpi_card("Cancelled orders", number(cancellation["Order Count"]), accent=False)
        with cols[1]:
            kpi_card("Cancelled quantity", number(cancellation["Quantity"]))

section_header("Product movement", "Movement classifications and review flags returned by the approved product-movement analysis.")
movement = analytics.get("movement_classified")
if movement is None or movement.empty:
    info_message("Product movement needs sufficient complete transaction history; no movement output is available for this dataset.")
else:
    classification_counts = movement["Movement Classification"].value_counts(dropna=False)
    movement_cards = [
        ("Fast moving", classification_counts.get("Fast Moving", 0), False),
        ("Steady moving", classification_counts.get("Regular Moving", 0), False),
        ("Slow moving", classification_counts.get("Slow Moving", 0), False),
        ("No movement", classification_counts.get("No Movement", 0), False),
    ]
    for column, (label, value, accent) in zip(st.columns(4, gap="small"), movement_cards, strict=True):
        with column:
            kpi_card(label, number(value), accent=accent)

    _render_product_movement_table(movement)
