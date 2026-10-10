"""Client-facing MCA product-priority page using approved results."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from src.prescriptive.mca import MCA_CRITERIA, MCA_WEIGHTS
from utils.components import empty_state, guard_protected_page, info_message, render_page_shell, section_header
from utils.state import (
    DataStatus,
    ensure_derived_outputs_for_active_dataset,
    get_data_status,
    get_mca_results,
    get_prescriptive_error_message,
    get_recommendation_results,
    get_risk_results,
)


PRIORITY_COLORS = {"High": "#B84F3F", "Medium": "#C99416", "Low": "#3D7A53"}


def _inject_priority_styles() -> None:
    st.markdown(
        """
        <style>
        .priority-card-title {
            margin:0;
            color:var(--tesph-text);
            font-size:1rem;
            font-weight:800;
        }
        .priority-card-copy {
            margin:.15rem 0 1rem;
            color:var(--tesph-text-muted);
            font-size:.82rem !important;
            line-height:1.45 !important;
        }
        .priority-weight-row {
            margin:.75rem 0;
        }
        .priority-weight-header {
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:.75rem;
            color:var(--tesph-text);
            font-size:.82rem;
            font-weight:800;
        }
        .priority-weight-criterion {
            font-weight:400;
        }
        .priority-progress {
            height:.45rem;
            border-radius:999px;
            background:#F1ECE3;
            overflow:hidden;
        }
        .priority-progress > span {
            display:block;
            height:100%;
            border-radius:999px;
            background:#D9980F;
        }
        .priority-total {
            margin:1rem 0 .75rem;
            padding:.75rem .85rem;
            border:1px solid var(--tesph-border);
            border-radius:var(--tesph-radius);
            background:#FFFFFF;
            color:var(--tesph-text);
            font-weight:800;
            display:flex;
            justify-content:space-between;
        }
        .priority-note {
            margin:.8rem 0 0;
            color:var(--tesph-text-muted);
            font-size:.78rem;
            line-height:1.45;
        }
        .priority-badge {
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-width:4.4rem;
            padding:.16rem .5rem;
            border-radius:999px;
            color:#FFFFFF;
            font-size:.74rem;
            font-weight:800;
        }
        .criterion-chip {
            display:inline-flex;
            margin:.12rem .2rem .12rem 0;
            padding:.16rem .45rem;
            border-radius:999px;
            background:#FFF7EA;
            color:#7A4E00;
            font-size:.72rem;
            font-weight:700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _frame(value: object) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _product_lookup(*frames: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for frame in frames:
        if {"SKU", "Product"}.issubset(frame.columns):
            columns = [column for column in ("SKU", "Product", "Category") if column in frame.columns]
            parts.append(frame[columns].dropna(subset=["SKU"]).drop_duplicates("SKU"))
    if not parts:
        return pd.DataFrame(columns=["SKU", "Product", "Category"])
    return pd.concat(parts, ignore_index=True).drop_duplicates("SKU")


def _approved_with_products(mca: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    result = mca.merge(lookup, on="SKU", how="left")
    result["Product"] = result["Product"].fillna(result["SKU"].astype(str))
    if "Priority Rank" not in result.columns and "SKU Priority Score" in result.columns:
        result = result.sort_values("SKU Priority Score", ascending=False, kind="stable").copy()
        result["Priority Rank"] = range(1, len(result) + 1)
    if "Priority Level" not in result.columns:
        if "SKU Priority Score" in result.columns:
            score = pd.to_numeric(result["SKU Priority Score"], errors="coerce")
            result["Priority Level"] = pd.cut(
                score,
                bins=[float("-inf"), 0.4, 0.7, float("inf")],
                labels=["Low", "Medium", "High"],
            ).astype(str)
        else:
            result["Priority Level"] = "Unranked"
    if "Priority Rank" not in result.columns:
        result["Priority Rank"] = range(1, len(result) + 1)
    return result.sort_values("Priority Rank", kind="stable")


def _weight_percent(weight: float) -> str:
    percent = float(weight) * 100
    if percent.is_integer():
        return f"{int(percent)}%"
    return f"{percent:.1f}%"


def _render_weights_panel() -> None:
    st.markdown('<p class="priority-card-title">Criteria Weights</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="priority-card-copy">Share of the overall prioritization score assigned to each criterion.</p>',
        unsafe_allow_html=True,
    )
    for criterion in MCA_CRITERIA:
        weight = float(MCA_WEIGHTS[criterion])
        percent = weight * 100
        st.markdown(
            f"""
            <div class="priority-weight-row">
                <div class="priority-weight-header">
                    <span class="priority-weight-criterion">{html.escape(criterion)}</span>
                    <span>{_weight_percent(weight)}</span>
                </div>
                <div class="priority-progress"><span style="width:{percent:.4f}%"></span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<div class="priority-total"><span>Total Weight</span><span>{_weight_percent(sum(MCA_WEIGHTS.values()))}</span></div>',
        unsafe_allow_html=True,
    )


def _render_chart(frame: pd.DataFrame) -> None:
    chart_data = frame.head(5).copy()
    if chart_data.empty:
        empty_state("No eligible products", "No products are available for MCA prioritization yet.")
        return
    chart_data["Chart Label"] = (
        chart_data["Product"].astype(str) + " (" + chart_data["SKU"].astype(str) + ")"
    )
    chart = {
        "mark": {"type": "bar", "cornerRadiusEnd": 4, "color": "#D9980F"},
        "encoding": {
            "y": {
                "field": "Chart Label",
                "type": "nominal",
                "sort": chart_data["Chart Label"].tolist(),
                "title": None,
                "axis": {"labelLimit": 220, "labelColor": "#625C54"},
            },
            "x": {
                "field": "SKU Priority Score",
                "type": "quantitative",
                "title": "MCA Score",
                "stack": None,
                "axis": {"grid": True, "gridColor": "#EAE5DC", "labelColor": "#625C54"},
            },
            "tooltip": [
                {"field": "Product", "type": "nominal"},
                {"field": "SKU", "type": "nominal"},
                {"field": "SKU Priority Score", "type": "quantitative", "format": ".3f"},
                {"field": "Priority Level", "type": "nominal"},
            ],
        },
        "height": 185,
        "padding": {"left": 12, "right": 12, "top": 10, "bottom": 10},
        "config": {"view": {"stroke": None}},
    }
    st.vega_lite_chart(chart_data, chart, use_container_width=True)


def _leading_criteria(row: pd.Series, limit: int = 2) -> list[str]:
    contributions = []
    for criterion in MCA_CRITERIA:
        column = f"Weighted {criterion}"
        if column in row and pd.notna(row[column]):
            contributions.append((criterion, float(row[column])))
    contributions.sort(key=lambda item: item[1], reverse=True)
    return [criterion for criterion, _ in contributions[:limit]]


def _why_text(row: pd.Series) -> str:
    leaders = _leading_criteria(row)
    if leaders:
        return "Strongest contributions: " + ", ".join(leaders)
    return "Details available from approved MCA score."


def _priority_badge(priority: str) -> str:
    color = PRIORITY_COLORS.get(str(priority), "#625C54")
    return f'<span class="priority-badge" style="background:{color}">{html.escape(str(priority))}</span>'


def _ranking_table(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame.rename(
        columns={
            "Priority Rank": "Rank",
            "SKU Priority Score": "MCA Score",
            "Priority Level": "Priority",
        }
    ).copy()
    table["Why Prioritized"] = table.apply(_why_text, axis=1)
    columns = ["Rank", "Product", "SKU", "MCA Score", "Priority", "Why Prioritized"]
    return table[[column for column in columns if column in table.columns]]


def _render_details(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    options = frame["SKU"].astype(str).tolist()
    labels = {
        str(row["SKU"]): f"{row['Product']} ({row['SKU']})"
        for _, row in frame.iterrows()
    }
    selected_sku = st.selectbox(
        "Review product details",
        options,
        format_func=lambda sku: labels.get(str(sku), str(sku)),
        key="priority_product_detail",
    )
    row = frame.loc[frame["SKU"].astype(str).eq(str(selected_sku))].iloc[0]
    leaders = _leading_criteria(row, limit=3)
    leader_text = ", ".join(leaders) if leaders else "the available approved MCA criteria"
    st.info(
        f"{row['Product']} received a {row['Priority Level']} priority ranking because its strongest weighted contributions came from {leader_text}."
    )

    detail_rows = []
    for criterion in MCA_CRITERIA:
        detail_rows.append(
            {
                "Criterion": criterion,
                "Approved Weight": _weight_percent(float(MCA_WEIGHTS[criterion])),
                "Raw Value": row.get(criterion),
                "Normalized Score": row.get(f"Normalized {criterion}"),
                "Weighted Contribution": row.get(f"Weighted {criterion}"),
            }
        )
    st.dataframe(
        pd.DataFrame(detail_rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Raw Value": st.column_config.NumberColumn("Raw Value", format="%.3f"),
            "Normalized Score": st.column_config.NumberColumn("Normalized Score", format="%.3f"),
            "Weighted Contribution": st.column_config.NumberColumn("Weighted Contribution", format="%.3f"),
        },
    )


def _missing_inputs_for_row(row: pd.Series) -> str:
    aliases = {
        "Projected Stock-Out Risk": "Risk Index",
        "Forecasted Demand": "Forecast Demand",
    }
    missing = []
    for criterion in MCA_CRITERIA:
        source = criterion if criterion in row.index else aliases.get(criterion)
        if source not in row.index or pd.isna(row.get(source)):
            missing.append(criterion)
    return ", ".join(missing) if missing else "Required MCA criteria unavailable in approved output"


def _not_ranked_products(risk: pd.DataFrame, recommendations: pd.DataFrame, ranked: pd.DataFrame) -> pd.DataFrame:
    if risk.empty or "SKU" not in risk.columns:
        return pd.DataFrame(columns=["SKU", "Product", "Missing Required Inputs"])
    ranked_skus = set(ranked["SKU"].astype(str)) if "SKU" in ranked.columns else set()
    base = risk.loc[~risk["SKU"].astype(str).isin(ranked_skus)].copy()
    if base.empty:
        return pd.DataFrame(columns=["SKU", "Product", "Missing Required Inputs"])
    if not recommendations.empty and "SKU" in recommendations.columns:
        extra_columns = [
            column
            for column in MCA_CRITERIA
            if column in recommendations.columns and column not in base.columns
        ]
        if extra_columns:
            base = base.merge(
                recommendations[["SKU", *extra_columns]].drop_duplicates("SKU"),
                on="SKU",
                how="left",
            )
    if "Product" not in base.columns:
        base["Product"] = base["SKU"].astype(str)
    base["Missing Required Inputs"] = base.apply(_missing_inputs_for_row, axis=1)
    return base[["SKU", "Product", "Missing Required Inputs"]].drop_duplicates("SKU")


guard_protected_page()
ensure_derived_outputs_for_active_dataset()
render_page_shell("Product Prioritization", "Decide - Prescriptive")
_inject_priority_styles()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing product priority.")
    st.stop()

mca = _frame(get_mca_results())
if mca.empty:
    error_message = get_prescriptive_error_message()
    if error_message:
        info_message(error_message)
    else:
        info_message("MCA requires a complete SKU forecast and a fresh, unambiguous current-stock match.")
    st.stop()

risk = _frame(get_risk_results())
recommendations = _frame(get_recommendation_results())
lookup = _product_lookup(recommendations, risk)
approved_ranked = _approved_with_products(mca, lookup)
not_ranked = _not_ranked_products(risk, recommendations, approved_ranked)

section_header(
    "Product Prioritization",
    "Review the current SKU-level product priority rankings generated from the active dataset.",
)

left, right = st.columns((0.28, 0.72), gap="small", vertical_alignment="top")

with left:
    with st.container(border=True):
        _render_weights_panel()

with right:
    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Top Priority Products</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Products with the highest overall MCA scores are shown first, based on the approved evaluation criteria.</p>',
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Product Prioritization Ranking</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Review each product ranking, priority level, and the main factors behind its MCA score.</p>',
            unsafe_allow_html=True,
        )
        ranking = _ranking_table(approved_ranked)
        st.dataframe(
            ranking,
            height=180,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "MCA Score": st.column_config.NumberColumn("MCA Score", format="%.3f"),
            },
        )

    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Priority Detail</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Inspect the approved criteria values and weighted contributions for a selected product.</p>',
            unsafe_allow_html=True,
        )
        _render_details(approved_ranked)

    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Approved MCA Output</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Audit the approved prioritization records currently powering this page.</p>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            approved_ranked,
            height=180,
            hide_index=True,
            use_container_width=True,
        )

    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Approved Criteria Weights</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Reference the current MCA criteria and their approved weighting.</p>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Criterion": criterion, "Weight": float(MCA_WEIGHTS[criterion])}
                    for criterion in MCA_CRITERIA
                ]
            ),
            height=180,
            hide_index=True,
            use_container_width=True,
            column_config={"Weight": st.column_config.NumberColumn("Weight", format="%.3f")},
        )
