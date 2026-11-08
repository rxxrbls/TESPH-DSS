"""Small, presentation-only helpers for approved analytics output tables."""

from __future__ import annotations
from html import escape

import pandas as pd
import streamlit as st


WARM_PALETTE = [
    "#FF5F00",  # Baby & Kids
    "#FFE45C",
    "#FF8C00",
    "#FFD000",
    "#FF6F1E",
    "#FFF09A",
    "#FFA500",
    "#F5C400",
    "#FF7F00",
    "#FFDC5E",
    "#E85D04",
    "#FFE990",
    "#FFB000",
    "#FFF3B0",
    "#F77F00",
    "#FFC300",
    "#FF9F1C",
    "#E6B800",
]
OTHER_CATEGORY_COLOR = "#D3C8BA"
CHART_CONFIG = {
    "view": {"stroke": "#E4DDD2"},
    "axis": {
        "labelColor": "#625C54",
        "titleColor": "#22201D",
        "gridColor": "#ECE6DC",
        "labelFont": "Inter, Segoe UI, Arial, sans-serif",
        "titleFont": "Inter, Segoe UI, Arial, sans-serif",
        "labelFontSize": 11,
        "titleFontSize": 12,
    },
    "legend": {
        "title": None,
        "orient": "right",
        "labelLimit": 220,
        "labelFontSize": 13,
        "symbolSize": 100,
        "rowPadding": 10,
        "offset": 34,
    },
}
VISUALIZATION_BORDER = "#E4DDD2"
VISUALIZATION_BACKGROUND = "#FFFFFF"
VISUALIZATION_PADDING = {
    "left": 24,
    "right": 24,
    "top": 15,
    "bottom": 15,
}


def _chart_height(height: int) -> int:
    return max(120, int(height) - VISUALIZATION_PADDING["top"] - VISUALIZATION_PADDING["bottom"])


def _visualization_chart_base(height: int) -> dict[str, object]:
    return {
        "background": VISUALIZATION_BACKGROUND,
        "padding": VISUALIZATION_PADDING,
        "height": _chart_height(height),
    }


def currency(value: object) -> str:
    """Format a supplied monetary value; no calculation is performed here."""
    return f"₱{float(value):,.2f}" if pd.notna(value) else "Not available"


def number(value: object, decimals: int = 0) -> str:
    return f"{float(value):,.{decimals}f}" if pd.notna(value) else "Not available"


def percent(value: object) -> str:
    return f"{float(value):.1%}" if pd.notna(value) else "Not available"


def _share_label(value: float) -> str:
    rounded = round(value, 1)
    return f"{int(rounded)}%" if rounded.is_integer() else f"{rounded:.1f}%"


def _category_color(category: object, domain: list[str]) -> str:
    category_text = str(category)
    if category_text not in domain:
        return OTHER_CATEGORY_COLOR
    return WARM_PALETTE[domain.index(category_text) % len(WARM_PALETTE)]


def render_category_mix(trends: pd.DataFrame, *, height: int = 360, limit: int = 6) -> bool:
    """Render category share of revenue from the approved sales-trends output."""
    needed = {"Category", "Net Revenue After Returns"}
    if trends is None or trends.empty or not needed.issubset(trends.columns):
        return False

    frame = trends.copy()
    frame["Net Revenue After Returns"] = pd.to_numeric(
        frame["Net Revenue After Returns"],
        errors="coerce",
    )

    category_domain = sorted(
        frame["Category"].dropna().astype(str).unique().tolist()
    )

    summary = (
        frame.dropna(subset=["Category", "Net Revenue After Returns"])
        .groupby("Category", as_index=False, sort=False)["Net Revenue After Returns"]
        .sum()
        .sort_values("Net Revenue After Returns", ascending=False)
    )

    summary = summary.loc[
        summary["Net Revenue After Returns"].gt(0)
    ].copy()

    total = float(summary["Net Revenue After Returns"].sum())

    if summary.empty or total <= 0:
        return False

    if len(summary) > limit:
        visible = summary.head(limit - 1).copy()

        other_value = summary.iloc[
            limit - 1:
        ]["Net Revenue After Returns"].sum()

        visible = pd.concat(
            [
                visible,
                pd.DataFrame(
                    [{
                        "Category": "Other",
                        "Net Revenue After Returns": other_value,
                    }]
                ),
            ],
            ignore_index=True,
        )
    else:
        visible = summary.head(limit).copy()

    visible["Share"] = (
        visible["Net Revenue After Returns"] / total * 100
    )

    visible["Color"] = visible["Category"].apply(
        lambda category: _category_color(
            category,
            category_domain,
        )
    )

    chart = {
        "mark": {
            "type": "arc",
            "innerRadius": 50,
            "outerRadius": 100,
        },

        "encoding": {
            "theta": {
                "field": "Share",
                "type": "quantitative",
            },
            "color": {
                "field": "Category",
                "type": "nominal",
                "scale": {
                    "domain": visible["Category"].astype(str).tolist(),
                    "range": visible["Color"].tolist(),
                },
                "legend": {
                    "title": None,
                    "orient": "right",
                    "direction": "vertical",
                    "labelLimit": 220,
                },
            },
            "tooltip": [
                {
                    "field": "Category",
                    "type": "nominal",
                    "title": "Category",
                },
                {
                    "field": "Share",
                    "type": "quantitative",
                    "title": "Share (%)",
                    "format": ".1f",
                },
                {
                    "field": "Net Revenue After Returns",
                    "type": "quantitative",
                    "title": "Net revenue (₱)",
                    "format": ",.2f",
                },
            ],
        },

        **_visualization_chart_base(height),

        "config": {
            **CHART_CONFIG,
            "legend": {
                **CHART_CONFIG["legend"],
                "orient": "right",
                "direction": "vertical",
                "layout": {
                    "right": {
                        "anchor": "middle",
                    },
                },
            },
        },
    }

    st.vega_lite_chart(
        visible,
        chart,
        width="stretch",
    )

    return True

def render_sales_trend(trends: pd.DataFrame, *, height: int = 360) -> bool:
    """Plot the existing category/month sales-trend output with DSS styling."""
    needed = {"Time", "Category", "Net Revenue After Returns"}

    if trends is None or trends.empty or not needed.issubset(trends.columns):
        return False

    frame = trends.copy()

    frame["Time"] = pd.to_datetime(
        frame["Time"],
        errors="coerce",
    )

    frame["Net Revenue After Returns"] = pd.to_numeric(
        frame["Net Revenue After Returns"],
        errors="coerce",
    )

    frame = frame.dropna(
        subset=["Time", "Category", "Net Revenue After Returns"]
    )

    if frame.empty:
        return False

    categories = sorted(
        frame["Category"].astype(str).unique().tolist()
    )


    chart = {
        "mark": {
            "type": "line",
            "point": {
                "filled": True,
                "size": 45,
            },
            "strokeWidth": 2.0,
        },

        "encoding": {
            "x": {
                "field": "Time",
                "type": "temporal",
                "title": "Month",
                "axis": {
                    "format": "%b %Y",
                    "labelAngle": -35,
                    "labelOverlap": "greedy",
                    "labelFlush": True,
                },
            },

            "y": {
                "field": "Net Revenue After Returns",
                "type": "quantitative",
                "title": "Net revenue after returns (₱)",
                "axis": {
                    "format": ",.0f",
                },
            },

            "color": {
                "field": "Category",
                "type": "nominal",
                "title": "Category",
                "scale": {
                    "domain": categories,
                    "range": WARM_PALETTE[:len(categories)],
                },
                "legend": None,
            },

            "tooltip": [
                {
                    "field": "Category",
                    "type": "nominal",
                    "title": "Category",
                },
                {
                    "field": "Time",
                    "type": "temporal",
                    "title": "Month",
                    "format": "%B %Y",
                },
                {
                    "field": "Net Revenue After Returns",
                    "type": "quantitative",
                    "title": "Net revenue (₱)",
                    "format": ",.2f",
                },
                {
                    "field": "Gross Demand",
                    "type": "quantitative",
                    "title": "Gross demand",
                    "format": ",.0f",
                },
            ],
        },

        **_visualization_chart_base(height),


        "config": CHART_CONFIG,
    }

    st.vega_lite_chart(
        frame,
        chart,
        width="stretch",
    )

    return True


def render_product_performance(products: pd.DataFrame, *, height: int = 310, limit: int = 10) -> bool:
    """Plot top products by the analytics pipeline's gross-revenue output."""
    needed = {"Product", "Gross Revenue"}
    if products is None or products.empty or not needed.issubset(products.columns):
        return False
    frame = products.copy()
    frame["Gross Revenue"] = pd.to_numeric(frame["Gross Revenue"], errors="coerce")
    frame = frame.dropna(subset=["Gross Revenue"]).nlargest(limit, "Gross Revenue").sort_values("Gross Revenue")
    if frame.empty:
        return False
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 3, "color": "#D9980F"},
        "encoding": {
            "y": {"field": "Product", "type": "nominal", "sort": "-x", "title": None, "axis": {"labelLimit": 190}},
            "x": {"field": "Gross Revenue", "type": "quantitative", "title": "Gross revenue (₱)", "axis": {"format": ",.0f"}},
            "tooltip": [
                {"field": "Product", "type": "nominal"},
                {"field": "Category", "type": "nominal"},
                {"field": "Gross Revenue", "type": "quantitative", "title": "Gross revenue (₱)", "format": ",.2f"},
                {"field": "Net Inventory Demand", "type": "quantitative", "title": "Net demand", "format": ",.0f"},
            ],
        },

        **_visualization_chart_base(height),
        "config": CHART_CONFIG,
    }
    st.vega_lite_chart(frame, chart, width="stretch")
    return True


def render_risk_summary(risk: pd.DataFrame, *, height: int = 240) -> bool:
    """Render a supplied risk-module result, never a UI-derived risk calculation."""
    if risk is None or risk.empty:
        return False
    level_column = next((column for column in ("stock_out_risk_level", "Stock-Out Risk Level", "Stock-Out Risk", "Risk Level") if column in risk.columns), None)
    if level_column is None:
        return False
    risk_order = [
        "Critical",
        "High",
        "Medium",
        "Low",
        "No Forecast Demand",
        "Insufficient Stock Data",
    ]
    summary = risk.groupby(level_column, dropna=False).size().rename("Products").reset_index().rename(columns={level_column: "Risk level"})
    summary["Risk level"] = summary["Risk level"].astype(str)
    summary["Sort"] = summary["Risk level"].map(
        {level: index for index, level in enumerate(risk_order)}
    ).fillna(len(risk_order))
    summary = summary.sort_values(["Sort", "Risk level"]).drop(columns="Sort")
    chart_height = min(height, max(120, len(summary) * 42))
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "y": {
                "field": "Risk level",
                "type": "nominal",
                "sort": risk_order,
                "title": None,
                "axis": {"labelLimit": 155},
            },
            "x": {
                "field": "Products",
                "type": "quantitative",
                "title": "Products",
                "axis": {"format": ",.0f"},
            },
            "color": {
                "field": "Risk level",
                "type": "nominal",
                "legend": None,
                "scale": {
                    "domain": risk_order,
                    "range": ["#8F3329", "#B84F3F", "#C99416", "#3D7A53", "#356F8C", "#81786D"],
                },
            },
            "tooltip": [{"field": "Risk level", "type": "nominal"}, {"field": "Products", "type": "quantitative"}],
        },

        "padding": {
                            "left": 24,
                            "right": 24,
                            "top": 15,
                            "bottom": 15,
                        },

        "height": chart_height,
        "padding": {"left": 4, "right": 10, "top": 8, "bottom": 6},
        "config": CHART_CONFIG,
    }
    st.vega_lite_chart(summary, chart, width="stretch")
    return True


def render_priority_recommendations(recommendations: pd.DataFrame, *, height: int = 310, limit: int = 4) -> bool:
    """Render the highest-priority rows from replenishment recommendations."""
    needed = {"Product", "Recommended Quantity"}
    if recommendations is None or recommendations.empty or not needed.issubset(recommendations.columns):
        return False

    frame = recommendations.copy()
    frame["Recommended Quantity"] = pd.to_numeric(frame["Recommended Quantity"], errors="coerce")
    frame = frame.dropna(subset=["Product", "Recommended Quantity"])
    if frame.empty:
        return False

    positive_recommendations = frame.loc[frame["Recommended Quantity"].gt(0)].copy()
    if not positive_recommendations.empty:
        frame = positive_recommendations

    priority_order = {"Immediate": 0, "High": 1, "Medium": 2, "Low": 3}
    if "Recommendation Priority" in frame:
        frame["_priority_sort"] = frame["Recommendation Priority"].map(priority_order).fillna(4)
    elif "Priority Level" in frame:
        frame["_priority_sort"] = frame["Priority Level"].map(priority_order).fillna(4)
    else:
        frame["_priority_sort"] = 4
    frame = frame.sort_values(
        ["_priority_sort", "Recommended Quantity", "Product"],
        ascending=[True, False, True],
    ).head(limit)

    rows: list[str] = []
    for _, row in frame.iterrows():
        product = escape(str(row["Product"]))
        quantity = number(row["Recommended Quantity"])
        priority = row.get("Recommendation Priority")
        if pd.isna(priority) or str(priority).strip() in {"", "None", "nan"}:
            priority = row.get("Priority Level")
        if pd.isna(priority) or str(priority).strip() in {"", "None", "nan"}:
            priority = "Monitor"
        badge_text = {
            "Immediate": "Urgent",
            "High": "Urgent",
            "Medium": "Medium",
            "Low": "Low",
            "None": "Monitor",
        }.get(str(priority), str(priority))
        badge = escape(badge_text)
        rows.append(
            '<div class="priority-row">'
            f'<div class="priority-item"><div class="priority-product">{product}</div>'
            f'<div class="priority-units">{quantity} units</div></div>'
            f'<span class="priority-badge">{badge}</span>'
            '</div>'
        )

    st.markdown(
        (
            '<section class="priority-list" '
            f'style="height:{int(height)}px; border-color:{VISUALIZATION_BORDER} !important; '
            f'background:{VISUALIZATION_BACKGROUND} !important;">'
            f'{"".join(rows)}'
            '</section>'
        ),
        unsafe_allow_html=True,
    )
    return True
