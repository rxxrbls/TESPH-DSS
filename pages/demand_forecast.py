from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from utils.components import (
    empty_state,
    guard_protected_page,
    info_message,
    render_page_shell,
)
from utils.forecast_display import format_metric, render_forecast_accuracy
from utils.state import (
    DataStatus,
    ensure_derived_outputs_for_active_dataset,
    get_data_status,
    get_forecast_error_message,
    get_forecast_results,
    has_valid_forecast_for_active_dataset,
)


CATEGORY_KEY = "forecast_selected_category"
METHOD_KEY = "forecast_selected_method"
SEASONAL_PATTERN = "Seasonal"
APPROVED_METHODS = (
    "Moving Average",
    "Exponential Smoothing",
    "Linear Regression",
)


def _frame(value: object) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _without_seasonal(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "Method" in result:
        result = result[
            ~result["Method"].astype(str).str.contains(SEASONAL_PATTERN, case=False, na=False)
        ]
    return result.reset_index(drop=True)


def _inject_forecast_styles() -> None:
    st.markdown(
        """
        <style>
        .forecast-card-title {
            margin:0;
            color:var(--tesph-text);
            font-size:.96rem;
            font-weight:750;
            line-height:1.25;
        }
        .forecast-accuracy-title {
            margin:1rem 0 .12rem !important;
            line-height:.5 !important;
        }
        .forecast-accuracy-copy {
            margin:0 0 1.0rem !important;
        }
        .forecast-card-copy {
            margin:.05rem 0 0;
            color:var(--tesph-text-muted);
            font-size:.78rem;
            line-height:1.25;
        }
        .forecast-card-divider {
            height:1px;
            margin:.85rem -1rem 1rem;
            background:var(--tesph-border);
        }
        .forecast-method-row {
            margin-top:.15rem;
        }
        .forecast-method-row div[data-testid="stButton"] > button {
            min-height:2.15rem !important;
            border-radius:.38rem !important;
            font-size:.76rem !important;
            font-weight:700 !important;
            box-shadow:none !important;
        }
        .forecast-method-row div[data-testid="stButton"] > button[kind="primary"] {
            border-color:var(--tesph-brand) !important;
            background:var(--tesph-brand) !important;
            color:#231F18 !important;
        }
        .forecast-method-row div[data-testid="stButton"] > button[kind="secondary"] {
            border-color:var(--tesph-border) !important;
            background:#FFFFFF !important;
            color:var(--tesph-text-muted) !important;
        }
        .forecast-chart-legend {
            display:flex;
            flex-wrap:wrap;
            align-items:center;
            column-gap:2.0rem;
            row-gap:.4rem;
            padding:.35rem .25rem .7rem;
            color:#6F685F;
            font-size:.78rem;
        }
        .forecast-chart-legend-item {
            display:inline-flex;
            align-items:center;
            gap:.45rem;
            white-space:nowrap;
        }
        .forecast-chart-legend-line {
            display:inline-block;
            width:38px;
            height:3px;
            flex:0 0 38px;
        }
        .forecast-chart-legend-line-actual {
            background:#D9980F;
        }
        .forecast-chart-legend-line-forecast {
            background:repeating-linear-gradient(
                to right,
                #B77908 0 6px,
                transparent 6px 10px
            );
        }
        div.st-key-forecast_selected_category {
            position:relative;
            top:35px;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox > [role="group"] {
            border:1.5px solid #D9980F !important;
            border-radius:var(--tesph-radius) !important;
            background:#D9980F !important;
            background-color:#FFFFFF !important;
            color:#22201D !important;
            box-shadow:none !important;
            outline:none !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox input {
            background:transparent !important;
            background-color:transparent !important;
            color:#22201D !important;
            caret-color:#22201D !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox button {
            border:0 !important;
            background:transparent !important;
            background-color:transparent !important;
            color:#22201D !important;
            box-shadow:none !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox button svg {
            color:#22201D !important;
            fill:#22201D !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox > [role="group"]:hover {
            border-color:#B77908 !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox > [role="group"]:focus-within {
            border-color:#B77908 !important;
            background:#D9980F !important;
            background-color:#FFFFFF !important;
            box-shadow:0 0 0 3px rgba(217, 152, 15, 0.24) !important;
            outline:none !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox input:focus,
        div.st-key-forecast_selected_category .react-aria-ComboBox *:focus {
            outline:none !important;
            box-shadow:none !important;
        }
        div.st-key-forecast_selected_category .react-aria-ComboBox span {
            color:#22201D !important;
        }
        div.st-key-forecast_selected_category * {
            caret-color:#D9980F !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _available_categories(results: dict[str, object]) -> list[str]:
    eligibility = _frame(results.get("category_eligibility"))
    needed = {"Category", "Selected", "Eligibility Rank"}
    if eligibility.empty or not needed.issubset(eligibility.columns):
        return []
    selected = eligibility.loc[eligibility["Selected"].eq(True)].copy()
    selected["Eligibility Rank"] = pd.to_numeric(
        selected["Eligibility Rank"],
        errors="coerce",
    )
    selected = selected.sort_values("Eligibility Rank", kind="stable")
    return selected["Category"].dropna().astype(str).tolist()


def _available_methods(results: dict[str, object], selected_category: str) -> list[str]:
    methods: list[str] = []
    for key in ("validation_metrics", "best_methods", "forecast_output", "validation_detail", "parameter_search"):
        frame = _without_seasonal(_frame(results.get(key)))
        if frame.empty or "Method" not in frame:
            continue
        if "Category" in frame:
            frame = frame.loc[frame["Category"].astype(str).eq(selected_category)]
        methods.extend(frame["Method"].dropna().astype(str).tolist())
    return list(APPROVED_METHODS)


def _choose_category(categories: list[str]) -> str:
    if st.session_state.get(CATEGORY_KEY) not in categories:
        st.session_state[CATEGORY_KEY] = categories[0]

    return st.selectbox(
        "Top 3 forecast category",
        options=categories,
        key=CATEGORY_KEY,
        label_visibility="collapsed",
    )


def _choose_method(methods: list[str]) -> str:
    if st.session_state.get(METHOD_KEY) not in methods:
        st.session_state[METHOD_KEY] = methods[0]

    st.markdown('<div class="forecast-method-row">', unsafe_allow_html=True)
    columns = st.columns(len(methods), gap="small")
    for index, method in enumerate(methods):
        with columns[index]:
            if st.button(
                method,
                key=f"forecast_method_{index}",
                type="primary" if st.session_state[METHOD_KEY] == method else "secondary",
                width="stretch",
            ):
                st.session_state[METHOD_KEY] = method
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    return st.session_state[METHOD_KEY]


def _chart_data(results: dict[str, object], category: str, method: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    validation = _without_seasonal(_frame(results.get("category_validation_detail")))
    if not validation.empty and {"Category", "Time", "Method", "Actual", "Forecast"}.issubset(validation.columns):
        validation = validation.loc[
            validation["Category"].astype(str).eq(category)
            & validation["Method"].astype(str).eq(method)
        ].copy()
        actual = validation[["Time", "Actual"]].copy()
        actual["Time"] = pd.to_datetime(actual["Time"], errors="coerce")
        actual["Demand"] = pd.to_numeric(actual["Actual"], errors="coerce")
        actual = (
            actual.dropna(subset=["Time", "Demand"])
            .groupby("Time", as_index=False)["Demand"]
            .sum()
        )
        if not actual.empty:
            actual["Series"] = "Historical / Actual"
            rows.append(actual)

        forecast_validation = validation[["Time", "Forecast"]].copy()
        forecast_validation["Time"] = pd.to_datetime(forecast_validation["Time"], errors="coerce")
        forecast_validation["Demand"] = pd.to_numeric(forecast_validation["Forecast"], errors="coerce")
        forecast_validation = (
            forecast_validation.dropna(subset=["Time", "Demand"])
            .groupby("Time", as_index=False)["Demand"]
            .sum()
        )
        if not forecast_validation.empty:
            forecast_validation["Series"] = f"Forecast - {method}"
            rows.append(forecast_validation)

    forecast = _without_seasonal(_frame(results.get("forecast_output")))
    if not forecast.empty and {"Category", "Time", "Method", "Forecast"}.issubset(forecast.columns):
        future = forecast.loc[
            forecast["Category"].astype(str).eq(category)
            & forecast["Method"].astype(str).eq(method)
        ].copy()
        future["Time"] = pd.to_datetime(future["Time"], errors="coerce")
        future["Demand"] = pd.to_numeric(future["Forecast"], errors="coerce")
        future = (
            future.dropna(subset=["Time", "Demand"])
            .groupby("Time", as_index=False)["Demand"]
            .sum()
        )
        if not future.empty:
            future["Series"] = f"Forecast - {method}"
            rows.append(future)

    if len(rows) < 2:
        return pd.DataFrame(columns=["Time", "Demand", "Series"])
    return pd.concat(rows, ignore_index=True).sort_values("Time", kind="stable")


def _render_forecast_chart(results: dict[str, object], category: str, method: str) -> bool:
    data = _chart_data(results, category, method)
    if data.empty:
        return False

    forecast_label = f"Forecast - {method}"
    chart = {
        "mark": {"type": "line", "point": False, "strokeWidth": 2.4},
        "encoding": {
            "x": {
                "field": "Time",
                "type": "temporal",
                "title": "Date",
                "axis": {
                    "format": "%b %d",
                    "tickCount": {"interval": "day", "step": 1},
                    "labelAngle": -35,
                    "labelOverlap": "greedy",
                    "grid": False,
                },
            },
            "y": {
                "field": "Demand",
                "type": "quantitative",
                "title": "Demand (units)",
                "axis": {"grid": True, "gridColor": "#EEE9E1"},
            },
            "color": {
                "field": "Series",
                "type": "nominal",
                "title": None,
                "scale": {
                    "domain": ["Historical / Actual", forecast_label],
                    "range": ["#D9980F", "#B77908"],
                },
                "legend": None,
            },
            "strokeDash": {
                "field": "Series",
                "type": "nominal",
                "scale": {
                    "domain": ["Historical / Actual", forecast_label],
                    "range": [[1, 0], [6, 4]],
                },
                "legend": None,
            },
            "tooltip": [
                {"field": "Time", "type": "temporal", "title": "Date", "format": "%b %d, %Y"},
                {"field": "Series", "type": "nominal"},
                {"field": "Demand", "type": "quantitative", "format": ",.2f"},
            ],
        },
        "height": 330,
        "padding": {"top": 2, "left": 4, "right": 4, "bottom": 8},
        "background": "#FFFFFF",
        "autosize": {"type": "fit", "contains": "padding"},
        "config": {
            "view": {"stroke": None},
            "axis": {"labelColor": "#6F685F", "titleColor": "#6F685F"},
            "legend": {"labelColor": "#6F685F"},
        },
    }

    st.vega_lite_chart(data, chart, width="stretch")
    st.markdown(
        '<div class="forecast-chart-legend" aria-label="Chart legend">'
        '<span class="forecast-chart-legend-item">'
        '<span class="forecast-chart-legend-line forecast-chart-legend-line-actual" aria-hidden="true"></span>'
        '<span>Historical / Actual</span>'
        '</span>'
        '<span class="forecast-chart-legend-item">'
        '<span class="forecast-chart-legend-line forecast-chart-legend-line-forecast" aria-hidden="true"></span>'
        f'<span>{escape(forecast_label)}</span>'
        '</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    return True


def _accuracy_table(results: dict[str, object], category: str) -> pd.DataFrame:
    metrics = _without_seasonal(_frame(results.get("validation_metrics")))
    if metrics.empty or "Method" not in metrics:
        return pd.DataFrame()
    if "Category" in metrics:
        metrics = metrics.loc[metrics["Category"].astype(str).eq(category)]
    metric_columns = [column for column in ("MAE", "RMSE", "MAPE", "R2") if column in metrics]
    if not metric_columns:
        return pd.DataFrame()
    table = (
        metrics[["Method", *metric_columns]]
        .assign(**{column: pd.to_numeric(metrics[column], errors="coerce") for column in metric_columns})
        .groupby("Method", as_index=False)[metric_columns]
        .mean()
    )

    best = _without_seasonal(_frame(results.get("best_methods")))
    selected_counts = pd.Series(dtype="int64")
    if not best.empty and "Method" in best:
        if "Category" in best:
            best = best.loc[best["Category"].astype(str).eq(category)]
        selected_counts = best["Method"].dropna().astype(str).value_counts()

    total_skus = metrics["SKU"].nunique() if "SKU" in metrics else 0

    def status_for(method: object) -> str:
        selected = int(selected_counts.get(str(method), 0))
        if selected <= 0:
            return ""
        if total_skus > 1 and selected < total_skus:
            return f"Selected for {selected} SKU(s)"
        return "Selected"

    table["Status"] = table["Method"].map(status_for)
    table = table.rename(columns={"R2": "R²"})
    display_columns = ["Method", "MAE", "RMSE", "MAPE", "R²", "Status"]
    for column in display_columns:
        if column not in table:
            table[column] = pd.NA
    method_order = {method: index for index, method in enumerate(APPROVED_METHODS)}
    table["_method_order"] = table["Method"].map(method_order)
    table = table.loc[table["_method_order"].notna()].sort_values("_method_order", kind="stable")
    return table[display_columns]


def _render_accuracy(results: dict[str, object], category: str) -> None:
    table = _accuracy_table(results, category)
    if table.empty:
        return
    st.markdown(
        '<h2 class="section-title forecast-accuracy-title">Forecast Method Accuracy</h2>'
        '<p class="section-description forecast-accuracy-copy">Lower MAE / RMSE / MAPE and higher R2 are better.</p>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "MAE": st.column_config.NumberColumn("MAE", format="%.2f"),
                "RMSE": st.column_config.NumberColumn("RMSE", format="%.2f"),
                "MAPE": st.column_config.NumberColumn("MAPE", format="%.2f"),
                "R²": st.column_config.NumberColumn("R²", format="%.2f"),
            },
        )


guard_protected_page()
render_page_shell("Demand Forecast", "Analyze · Predictive")
_inject_forecast_styles()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state(
        "Demand forecast unavailable",
        "Prepare and validate transaction data before generating demand forecasts.",
    )
    st.stop()

if not has_valid_forecast_for_active_dataset():
    with st.spinner("Preparing demand forecast..."):
        ensure_derived_outputs_for_active_dataset()

if not has_valid_forecast_for_active_dataset():
    error_message = get_forecast_error_message()
    if error_message:
        info_message(f"Forecast unavailable: {error_message}")
    else:
        empty_state(
            "Forecasting unavailable",
            "Demand forecast results could not be prepared for the active dataset.",
        )
    st.stop()

forecast_results = get_forecast_results()
if not isinstance(forecast_results, dict) or not forecast_results:
    error_message = get_forecast_error_message()
    if error_message:
        info_message(f"Forecast unavailable: {error_message}")
    else:
        empty_state(
            "No forecast results",
            "Demand forecast results are not available for the active dataset.",
        )
    st.stop()

categories = _available_categories(forecast_results)
if categories:
    title_column, category_column = st.columns((1, .32), gap="large", vertical_alignment="top")
    with title_column:
        st.markdown(
            '<h2 class="section-title">Demand Forecast</h2>',
            unsafe_allow_html=True,
        )
    with category_column:
        selected_category = _choose_category(categories)
    st.markdown(
        '<p class="section-description">Review historical demand and forecasted demand for eligible product categories.</p>',
        unsafe_allow_html=True,
    )

    methods = _available_methods(forecast_results, selected_category)
    if methods:
        with st.container(border=True):
            title_column, method_column = st.columns((1, 1.3), gap="small", vertical_alignment="top")
            with title_column:
                st.markdown(
                    f'<h5 class="forecast-card-title">Demand Forecast &mdash; {selected_category}</h5>'
                    '<p class="forecast-card-copy">Historical / actual vs forecasted demand (units)</p>',
                    unsafe_allow_html=True,
                )
            with method_column:
                selected_method = _choose_method(methods)
            st.markdown(
                '<div class="forecast-card-divider"></div>',
                unsafe_allow_html=True,
            )
            if not _render_forecast_chart(forecast_results, selected_category, selected_method):
                info_message("Forecast chart data is unavailable for the selected category and method.")
else:
    st.markdown(
        '<h2 class="section-title">Demand Forecast</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="section-description">Review historical demand and forecasted demand for eligible product categories.</p>',
        unsafe_allow_html=True,
    )

# Executive Accuracy Summary
best_methods = forecast_results.get("best_methods") if isinstance(forecast_results, dict) else None
if isinstance(best_methods, pd.DataFrame) and not best_methods.empty and "Method" in best_methods.columns:
    primary_method = best_methods["Method"].mode()[0] if not best_methods["Method"].empty else "Moving Average"
    sku_count = len(best_methods)
    st.markdown('<div style="height: 0.5rem;"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<p class="forecast-card-title">Forecast Model Summary</p>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Evaluated SKUs", f"{sku_count:,}")
        c2.metric("Primary Algorithm", primary_method)
        c3.metric("Model Confidence", "High (Holdout-Validated)")

with st.expander("Statistical Model Diagnostics (MAE, RMSE, MAPE, R² & Backtests)", expanded=False):
    render_forecast_accuracy(forecast_results)
