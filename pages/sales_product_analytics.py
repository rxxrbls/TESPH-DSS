"""Descriptive sales and product analytics from the approved analytics pipeline."""

from html import escape

import pandas as pd
import streamlit as st

from utils.analytics_display import currency, number, percent, render_product_performance, render_sales_trend
from utils.components import empty_state, guard_protected_page, info_message, kpi_card, primary_button, render_page_shell, section_header
from utils.movement_display import movement_table_views
from utils.state import DataStatus, ensure_derived_outputs_for_active_dataset, get_analytics_error_message, get_analytics_results, get_data_status, get_prepared_transactions, get_recommendation_results, get_risk_results
from analytics_pipeline import run_analytics_pipeline


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


def _reset_analytics_filters(min_date, max_date, categories: list[str]) -> None:
    st.session_state["analytics_date_range_draft"] = (min_date.date(), max_date.date())
    st.session_state["analytics_category_draft"] = []
    st.session_state["analytics_product_draft"] = ""
    st.session_state["analytics_applied_filters"] = None


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


def _render_product_movement_table(movement: pd.DataFrame, *, preview_limit: int = 12) -> None:
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
        .drop(columns="_movement_priority")
    )

    def render_html_table(rows_frame: pd.DataFrame) -> None:
        rows = []
        for _, row in rows_frame.iterrows():
            product = escape(str(row.get("Product", "Not available")))
            category = escape(str(row.get("Category", "Not available")))
            units = number(row.get("Units Sold"))
            stock = "Not available" if pd.isna(row.get("Current Stock")) else number(row.get("Current Stock"))
            movement_label = escape(str(row.get("Movement", "Not available")))
            risk_value = row.get("Stock-Out Risk")
            risk_label = "Not available" if pd.isna(risk_value) else escape(str(risk_value))
            rows.append(
                "<tr>"
                f"<td class='movement-product'>{product}</td><td>{category}</td>"
                f"<td class='numeric'>{units}</td><td class='numeric'>{stock}</td>"
                f"<td><span class='movement-badge {_badge_class(movement_label)}'>{movement_label}</span></td>"
                f"<td><span class='movement-badge {_badge_class(risk_label)}'>{risk_label}</span></td></tr>"
            )
        st.markdown(
            "<div class='movement-table-wrap'><table class='movement-table'>"
            "<thead><tr><th>Product</th><th>Category</th><th>Units sold</th><th>Current stock</th><th>Movement</th><th>Stock-out risk</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <style>
        .movement-table-wrap { height:14.5rem; margin-bottom:1rem; overflow:auto; border:1px solid #E4DDD2; border-radius:.45rem; background:#FFFFFF; }
        .movement-table { width:100%; border-collapse:collapse; font-size:.88rem; color:#3A3835; }
        .movement-table th { position:sticky; top:0; z-index:1; padding:.55rem .8rem; border-bottom:1px solid #E4DDD2; background:#FFFFFF; color:#8A8379; font-size:.72rem; font-weight:800; text-transform:uppercase; text-align:left; white-space:nowrap; }
        .movement-table td { height:2.4rem; padding:.3rem .8rem; border-bottom:1px solid #EDE7DC; vertical-align:middle; white-space:nowrap; }
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
    if display.empty:
        info_message("No product movement records are available for the selected filters.")
        return
    preview, all_products = movement_table_views(display, preview_limit)
    render_html_table(preview)
    with st.expander(f"View All ({len(all_products):,} Products)", expanded=False):
        st.dataframe(
            all_products,
            hide_index=True,
            width="stretch",
            height=520,
            column_config={
                "Units Sold": st.column_config.NumberColumn("Units Sold", format="%,.0f"),
                "Current Stock": st.column_config.NumberColumn("Current Stock", format="%,.0f"),
            },
        )


guard_protected_page()
render_page_shell("Sales & Product Analytics", "Analyze · Descriptive")
st.markdown(
    "<style>.analytics-page-title { margin-top:1rem !important; }</style>"
    "<h2 class='section-title analytics-page-title'>Sales &amp; Product Analytics</h2>"
    "<p class='section-description'>Analyze sales performance, product movement, and key business insights.</p>",
    unsafe_allow_html=True,
)
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

transactions = get_prepared_transactions()
transactions = transactions if isinstance(transactions, pd.DataFrame) else pd.DataFrame()
if transactions.empty or not {"order_date", "final_category"}.issubset(transactions.columns):
    filtered_transactions = transactions
    info_message("Date/category filters are unavailable because cleaned transaction fields are missing.")
else:
    tx_dates = pd.to_datetime(transactions["order_date"], errors="coerce")
    valid_dates = tx_dates.dropna()
    if valid_dates.empty:
        filtered_transactions = transactions.iloc[0:0].copy()
        info_message("Date filtering is unavailable because the cleaned transactions contain no valid order dates.")
    else:
        min_date, max_date = valid_dates.min(), valid_dates.max()
        categories = sorted(transactions["final_category"].dropna().astype(str).unique())
        product_fields = [c for c in ("SKU Reference No.", "final_base_product_name", "Product Name") if c in transactions]
        st.session_state.setdefault("analytics_date_range_draft", (min_date.date(), max_date.date()))
        if not isinstance(st.session_state.get("analytics_category_draft"), list):
            st.session_state["analytics_category_draft"] = []
        st.session_state.setdefault("analytics_product_draft", "")
        st.markdown("""<style>
        .business-insight-value { font-size:.95rem !important; }
        .business-insight-product { font-size:.8rem !important; }
        div.st-key-business-insights-cards .kpi-card { height:7.5rem !important; min-height:7.5rem !important; box-sizing:border-box !important; }
        div[data-testid="stDateInput"] label,div[data-testid="stMultiSelect"] label,div[data-testid="stTextInput"] label { font-weight:650; color:#403A35; }
        div[data-testid="stDateInput"] [data-baseweb="input"],div[data-testid="stMultiSelect"] [data-baseweb="select"],div[data-testid="stTextInput"] [data-baseweb="input"] { border:1px solid var(--tesph-border-strong) !important; border-radius:var(--tesph-radius-sm) !important; background:var(--tesph-surface) !important; box-shadow:none !important; }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.analytics-filter-bar-anchor) { border:1px solid #E9E0D8 !important; border-radius:1rem !important; background:linear-gradient(100deg,#FFFCFA,#FFFFFF) !important; padding:0 !important; box-shadow:0 4px 14px rgba(77,52,32,.05); }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.analytics-filter-bar-anchor) > div { padding:.1rem .75rem .55rem !important; }
        div[data-testid="stElementContainer"]:has(.analytics-filter-bar-anchor) { display:none !important; }
        </style>""", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown('<div class="analytics-filter-bar-anchor"></div>', unsafe_allow_html=True)
            f1, f2, f3, f4, f5 = st.columns((1.2, 1.1, 1.25, .68, .52), gap="small", vertical_alignment="bottom")
            with f1:
                draft_date_range = st.date_input("Date Range", value=(min_date.date(), max_date.date()), min_value=min_date.date(), max_value=max_date.date(), key="analytics_date_range_draft")
            with f2:
                draft_categories = st.multiselect("Category", categories, key="analytics_category_draft", placeholder="All Categories")
            with f3:
                draft_product = st.text_input("Product / SKU search", key="analytics_product_draft", placeholder="Search product or SKU")
            with f4:
                st.markdown('<div style="height:0rem"></div>', unsafe_allow_html=True)
                apply_clicked = st.button("Apply Filters", key="analytics_apply_filters", type="primary", width="stretch")
            with f5:
                st.markdown('<div style="height:0rem"></div>', unsafe_allow_html=True)
                st.button(
                    "↶ Reset",
                    key="analytics_reset_filters",
                    width="stretch",
                    on_click=_reset_analytics_filters,
                    args=(min_date, max_date, categories),
                )
        if apply_clicked:
            st.session_state["analytics_applied_filters"] = {
                "date_range": tuple(draft_date_range) if isinstance(draft_date_range, (tuple, list)) else None,
                "categories": list(draft_categories),
                "product": draft_product,
            }
        applied = st.session_state.get("analytics_applied_filters") or {
            "date_range": (min_date.date(), max_date.date()),
            "categories": [], "product": "",
        }
        date_range = applied.get("date_range")
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            filtered_transactions = transactions.loc[tx_dates.between(start, end)].copy()
        else:
            filtered_transactions = transactions.iloc[0:0].copy()
        if applied.get("categories"):
            filtered_transactions = filtered_transactions.loc[filtered_transactions["final_category"].astype(str).isin(applied["categories"])]
        if str(applied.get("product", "")).strip():
            product_search = str(applied["product"]).strip()
            product_match = pd.Series(False, index=filtered_transactions.index)
            for col in product_fields:
                product_match |= filtered_transactions[col].astype("string").str.contains(product_search, case=False, regex=False, na=False)
            filtered_transactions = filtered_transactions.loc[product_match]

if filtered_transactions.empty:
    section_header("Sales summary", "No transaction rows match the selected filters.")
    st.info("Adjust or reset the filters to view analytics.")
    st.stop()

filtered_analytics = run_analytics_pipeline(filtered_transactions)
summary = filtered_analytics["sales_summary"].iloc[0]
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
products = filtered_analytics.get("product_performance")
if not render_product_performance(products, height=340):
    info_message("Product performance data is unavailable for this processed dataset.")

section_header("Sales trends", "Monthly category trends using net revenue after returns.")
sales_trends = filtered_analytics.get("sales_trends")
if not render_sales_trend(sales_trends, height=340):
    info_message("Sales trend data is unavailable for this processed dataset.")

returns_column, cancellations_column = st.columns(2, gap="large")
with returns_column:
    section_header("Returns", "Return indicators from order and returned-quantity statuses.")
    returns = filtered_analytics.get("return_indicators")
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
    status = filtered_analytics.get("order_status")
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

section_header("Product movement", "Existing approved movement classifications for products present in the selected filters.")
movement = analytics.get("movement_classified")
if movement is not None and not movement.empty:
    filtered_products = filtered_analytics.get("product_performance", pd.DataFrame())
    keys = filtered_products["Product Key"].dropna().unique() if "Product Key" in filtered_products else []
    movement = movement.loc[movement["Product Key"].isin(keys)] if "Product Key" in movement else movement.iloc[0:0]
if movement is None or movement.empty:
    info_message("Product movement needs sufficient complete transaction history; no movement output is available for this dataset.")
else:
    classification_counts = movement["Movement Classification"].value_counts(dropna=False)
    movement_cards = [
        ("Fast moving", classification_counts.get("Fast Moving", 0), False),
        ("Regular moving", classification_counts.get("Regular Moving", 0), False),
        ("Slow moving", classification_counts.get("Slow Moving", 0), False),
        ("No movement", classification_counts.get("No Movement", 0), False),
    ]
    for column, (label, value, accent) in zip(st.columns(4, gap="small"), movement_cards, strict=True):
        with column:
            kpi_card(label, number(value), accent=accent)

    _render_product_movement_table(movement)

with st.expander("Underperforming Products Requiring Attention", expanded=False):
    products_for_review = filtered_analytics.get("products_for_review")
    if products_for_review is None:
        info_message("The product review output is unavailable for the current filtered data.")
    elif products_for_review.empty:
        info_message("No products require attention in the current filtered results.")
    else:
        st.caption("Products appear here under the existing movement and business-owner review rules. Available movement and review indicators are shown without adding thresholds.")
        st.dataframe(products_for_review, hide_index=True, width="stretch")

section_header("Key Business Insights", "Highlights from the filtered results. Return rate is returned units / gross demand; movement uses its configured historical window.")
performance = filtered_analytics.get("product_performance", pd.DataFrame())
if performance is not None and not performance.empty:
    business_insights = []
    revenue_col = "Gross Revenue" if "Gross Revenue" in performance else None
    if revenue_col:
        top = performance.sort_values(revenue_col, ascending=False).iloc[0]
        product_name = escape(str(top.get("Product", top.get("SKU", "Product"))))
        business_insights.append((
            "Top gross revenue product",
            f'<span class="business-insight-value"><span class="business-insight-product">{product_name}</span> — {currency(top[revenue_col])}</span>',
        ))
    returns_by_category = filtered_analytics.get("return_indicators_by_category", pd.DataFrame())
    if returns_by_category is not None and not returns_by_category.empty and "Return Quantity Rate" in returns_by_category:
        risks = returns_by_category.dropna(subset=["Return Quantity Rate"]).sort_values("Return Quantity Rate", ascending=False)
        if not risks.empty:
            row = risks.iloc[0]
            category_name = escape(str(row["Category"]))
            business_insights.append((
                "Highest return quantity rate",
                f'<span class="business-insight-value">{category_name} — {percent(row["Return Quantity Rate"])} '
                f'({number(row.get("Returned Quantity"))} / {number(row.get("Gross Demand"))} units)</span>',
            ))
    if movement is not None and not movement.empty and "Movement Classification" in movement:
        fast = movement.loc[movement["Movement Classification"].eq("Fast Moving")]
        if not fast.empty:
            label_col = "Product" if "Product" in fast else "SKU"
            fast_products = (
                '<span class="business-insight-product">, </span>'.join(
                    f'<span class="business-insight-product">{escape(name)}</span>'
                    for name in fast[label_col].dropna().astype(str).head(3)
                )
            )
        else:
            fast_products = "None classified"
        business_insights.append(("Fast-moving products", fast_products))
    if business_insights:
        with st.container(key="business-insights-cards"):
            for column, (label, value) in zip(
                st.columns(len(business_insights), gap="small"),
                business_insights,
                strict=True,
            ):
                with column:
                    kpi_card(label, value, accent=True)
    else:
        info_message("No key business insights are available for the filtered results.")
elif performance is None or performance.empty:
    info_message("No product-level results are available for these filters.")
