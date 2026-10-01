"""Small, presentation-only helpers for approved analytics output tables."""

from __future__ import annotations

import pandas as pd
import streamlit as st


WARM_PALETTE = ["#EEAC17", "#6B6259", "#B97832", "#9E8E7C", "#D6C5A8"]


def currency(value: object) -> str:
    """Format a supplied monetary value; no calculation is performed here."""
    return f"₱{float(value):,.2f}" if pd.notna(value) else "Not available"


def number(value: object, decimals: int = 0) -> str:
    return f"{float(value):,.{decimals}f}" if pd.notna(value) else "Not available"


def percent(value: object) -> str:
    return f"{float(value):.1%}" if pd.notna(value) else "Not available"


def render_sales_trend(trends: pd.DataFrame, *, height: int = 300) -> bool:
    """Plot the existing category/month sales-trend output with warm styling."""
    needed = {"Time", "Category", "Net Revenue After Returns"}
    if trends is None or trends.empty or not needed.issubset(trends.columns):
        return False
    frame = trends.copy()
    frame["Time"] = pd.to_datetime(frame["Time"], errors="coerce")
    frame = frame.dropna(subset=["Time", "Net Revenue After Returns"])
    if frame.empty:
        return False
    chart = {
        "mark": {"type": "line", "point": {"filled": True, "size": 35}, "strokeWidth": 2.4},
        "encoding": {
            "x": {"field": "Time", "type": "temporal", "title": "Month", "axis": {"format": "%b %Y", "labelAngle": -35}},
            "y": {"field": "Net Revenue After Returns", "type": "quantitative", "title": "Net revenue after returns", "axis": {"format": "₱,.0f"}},
            "color": {"field": "Category", "type": "nominal", "title": "Category", "scale": {"range": WARM_PALETTE}},
            "tooltip": [
                {"field": "Time", "type": "temporal", "title": "Month", "format": "%b %Y"},
                {"field": "Category", "type": "nominal"},
                {"field": "Net Revenue After Returns", "type": "quantitative", "title": "Net revenue", "format": "₱,.2f"},
                {"field": "Gross Demand", "type": "quantitative", "title": "Gross demand", "format": ",.0f"},
            ],
        },
        "height": height,
        "config": {"view": {"stroke": "#E8E1D8"}, "axis": {"labelColor": "#6B6259", "titleColor": "#1F1F1F", "gridColor": "#F0EBE3"}},
    }
    st.vega_lite_chart(frame, chart, use_container_width=True)
    return True


def render_product_performance(products: pd.DataFrame, *, height: int = 320, limit: int = 10) -> bool:
    """Plot top products by the analytics pipeline's gross-revenue output."""
    needed = {"Product", "Gross Revenue"}
    if products is None or products.empty or not needed.issubset(products.columns):
        return False
    frame = products.nlargest(limit, "Gross Revenue").sort_values("Gross Revenue").copy()
    if frame.empty:
        return False
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 3, "color": "#EEAC17"},
        "encoding": {
            "y": {"field": "Product", "type": "nominal", "sort": "-x", "title": None, "axis": {"labelLimit": 170}},
            "x": {"field": "Gross Revenue", "type": "quantitative", "title": "Gross revenue", "axis": {"format": "₱,.0f"}},
            "tooltip": [
                {"field": "Product", "type": "nominal"},
                {"field": "Category", "type": "nominal"},
                {"field": "Gross Revenue", "type": "quantitative", "title": "Gross revenue", "format": "₱,.2f"},
                {"field": "Net Inventory Demand", "type": "quantitative", "title": "Net demand", "format": ",.0f"},
            ],
        },
        "height": height,
        "config": {"view": {"stroke": "#E8E1D8"}, "axis": {"labelColor": "#6B6259", "titleColor": "#1F1F1F", "gridColor": "#F0EBE3"}},
    }
    st.vega_lite_chart(frame, chart, use_container_width=True)
    return True


def render_risk_summary(risk: pd.DataFrame, *, height: int = 240) -> bool:
    """Render a supplied risk-module result, never a UI-derived risk calculation."""
    if risk is None or risk.empty:
        return False
    level_column = next((column for column in ("stock_out_risk_level", "Stock-Out Risk Level", "Stock-Out Risk", "Risk Level") if column in risk.columns), None)
    if level_column is None:
        return False
    summary = risk.groupby(level_column, dropna=False).size().rename("Products").reset_index().rename(columns={level_column: "Risk level"})
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {"field": "Risk level", "type": "nominal", "title": None},
            "y": {"field": "Products", "type": "quantitative", "title": "Products"},
            "color": {"field": "Risk level", "type": "nominal", "legend": None, "scale": {"domain": ["High", "Medium", "Low"], "range": ["#B85B48", "#D3A72B", "#6E9479"]}},
            "tooltip": [{"field": "Risk level", "type": "nominal"}, {"field": "Products", "type": "quantitative"}],
        },
        "height": height,
        "config": {"view": {"stroke": "#E8E1D8"}, "axis": {"labelColor": "#6B6259", "titleColor": "#1F1F1F", "gridColor": "#F0EBE3"}},
    }
    st.vega_lite_chart(summary, chart, use_container_width=True)
    return True
