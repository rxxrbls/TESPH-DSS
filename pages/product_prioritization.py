"""Client-facing MCA product-priority page using approved results."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from src.prescriptive.mca import MCA_CRITERIA as LEGACY_CRITERIA, MCA_WEIGHTS as LEGACY_WEIGHTS
from three_criterion_mca import CRITERIA as THREE_CRITERIA, RATE as THREE_RATE, SCENARIOS
from utils.components import empty_state, guard_protected_page, info_message, render_page_shell, section_header
from utils.state import (
    DataStatus,
    ensure_derived_outputs_for_active_dataset,
    get_analytics_results,
    get_data_status,
    get_forecast_error_message,
    get_forecast_results,
    get_mca_audit,
    get_mca_results,
    get_prescriptive_error_message,
    get_recommendation_results,
    get_risk_results,
)


PRIORITY_COLORS = {"High": "#B84F3F", "Medium": "#C99416", "Low": "#3D7A53"}


def _get_active_criteria_and_weights(mca: pd.DataFrame, audit: pd.DataFrame | None) -> tuple[tuple[str, ...], dict[str, float]]:
    is_three = (audit is not None and THREE_RATE in audit.columns) or (not mca.empty and THREE_RATE in mca.columns)
    if is_three or (audit is not None and not audit.empty) or not mca.empty:
        # TA-approved three-criterion MCA baseline is equal-thirds
        if is_three or not any(c in mca.columns for c in ("Profit Margin", "Supplier Lead Time")):
            return THREE_CRITERIA, SCENARIOS["equal_thirds"]
    return tuple(LEGACY_CRITERIA), {k: float(v) for k, v in LEGACY_WEIGHTS.items()}


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
            padding:.2rem .65rem;
            border-radius:999px;
            color:#FFFFFF;
            font-size:.75rem;
            font-weight:700;
            text-transform:capitalize;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _frame(value: object) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame()


def _weight_percent(weight: float) -> str:
    return f"{weight * 100:.2f}%".rstrip("0").rstrip(".") + "%"


def _product_lookup(recommendations: pd.DataFrame, risk: pd.DataFrame) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for frame in (recommendations, risk):
        if frame.empty or "SKU" not in frame.columns:
            continue
        for _, row in frame.iterrows():
            sku = str(row["SKU"])
            lookup.setdefault(
                sku,
                {
                    "Product": str(row.get("Product", sku)),
                    "Category": str(row.get("Category", "Uncategorized")),
                },
            )
    return lookup


def _approved_with_products(mca: pd.DataFrame, lookup: dict[str, dict[str, str]]) -> pd.DataFrame:
    if mca.empty:
        return mca
    frame = mca.copy()
    if "Product" not in frame.columns:
        frame["Product"] = frame["SKU"].astype(str).map(lambda sku: lookup.get(sku, {}).get("Product", sku))
    if "Category" not in frame.columns:
        frame["Category"] = frame["SKU"].astype(str).map(
            lambda sku: lookup.get(sku, {}).get("Category", "Uncategorized")
        )
    return frame


def _render_weights_panel(criteria: tuple[str, ...], weights: dict[str, float]) -> None:
    st.markdown('<p class="priority-card-title">Approved Weights</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="priority-card-copy">Relative importance applied across the approved evaluation criteria.</p>',
        unsafe_allow_html=True,
    )
    total_weight = 0.0
    for criterion in criteria:
        weight = float(weights.get(criterion, 0.0))
        total_weight += weight
        percent_label = _weight_percent(weight)
        progress_width = min(max(weight * 100.0, 0.0), 100.0)
        st.markdown(
            f"""
            <div class="priority-weight-row">
                <div class="priority-weight-header">
                    <span class="priority-weight-criterion">{html.escape(criterion)}</span>
                    <span>{percent_label}</span>
                </div>
                <div class="priority-progress">
                    <span style="width:{progress_width:.2f}%;"></span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<div class="priority-total"><span>Total Weight</span><span>{_weight_percent(total_weight)}</span></div>',
        unsafe_allow_html=True,
    )


def _render_details(frame: pd.DataFrame, criteria: tuple[str, ...], weights: dict[str, float]) -> None:
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
    st.info(
        f"{row['Product']} received a {row.get('Priority Level', 'N/A')} priority ranking based on the active MCA criteria."
    )

    detail_rows = []
    for criterion in criteria:
        weight = float(weights.get(criterion, 0.0))
        raw_val = row.get(criterion)
        norm_val = row.get(f"Normalized {criterion}")
        contrib_val = row.get(f"Weighted {criterion}")
        if norm_val is None and pd.notna(raw_val):
            norm_val = raw_val
        if contrib_val is None and pd.notna(norm_val) and pd.notna(weight):
            try:
                contrib_val = float(norm_val) * weight
            except (ValueError, TypeError):
                contrib_val = None
        detail_rows.append(
            {
                "Criterion": criterion,
                "Approved Weight": _weight_percent(weight),
                "Raw Value": raw_val,
                "Normalized Score": norm_val,
                "Weighted Contribution": contrib_val,
            }
        )

    st.dataframe(
        pd.DataFrame(detail_rows),
        hide_index=True,
        width="stretch",
    )


def _why_text(row: pd.Series) -> str:
    leaders = []
    for criterion in THREE_CRITERIA:
        col = f"Weighted {criterion}"
        if col in row and pd.notna(row[col]):
            leaders.append((criterion, float(row[col])))
    leaders.sort(key=lambda x: x[1], reverse=True)
    if leaders:
        return "Strongest contributions: " + ", ".join([c for c, _ in leaders[:2]])
    return "Details available from approved MCA score."


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


guard_protected_page()
ensure_derived_outputs_for_active_dataset()
render_page_shell("Product Prioritization", "Decide · Prescriptive")
_inject_priority_styles()

if get_data_status() is not DataStatus.DATA_READY:
    empty_state("No data available", "Upload and process a Shopee export before reviewing product priority.")
    st.stop()

analytics = get_analytics_results() or {}
forecast_results = get_forecast_results() or {}
forecast = forecast_results.get("forecast_output")
if forecast is None or forecast.empty:
    info_message("Forecasted demand is not available for MCA because this dataset has no eligible SKU forecast. See the Forecast eligibility audit.")
    if get_forecast_error_message():
        info_message(get_forecast_error_message())


audit = get_mca_audit()
is_three = audit is not None and THREE_RATE in audit.columns if audit is not None else False

with st.expander("Decision Audit Trail & Criteria Diagnostics", expanded=False):
    if is_three:
        st.caption("Three-criterion MCA: Sales Velocity, Forecasted Demand, and Recorded Return/Refund Quantity Rate (%). TA-approved equal-third baseline weights; historical validation accepted by TA. Complete eligible SKUs only; Min-Max normalization, valid constant criteria = 0.5, missing/unresolved criteria = N/A and exclusion. Selected request-date coverage is not lifetime return history.")
    else:
        st.caption("Legacy five criteria: Sales Velocity, Profit Margin, Supplier Lead Time, Forecasted Demand, Return Rate. Upload the cleaned return/refund evidence under Data Upload to activate the TA-approved three-criterion assessment. Legacy weights: 20% each.")

    if audit is not None and not audit.empty:
        display_audit = audit.copy()
        display_criteria = THREE_CRITERIA if is_three else LEGACY_CRITERIA
        for criterion in display_criteria:
            if criterion in display_audit.columns:
                display_audit[criterion] = audit[criterion].map(
                    lambda value: "N/A" if pd.isna(value) else format(value, ".6g")
                )
        st.dataframe(display_audit, hide_index=True)
        st.download_button("Download MCA readiness audit", audit.to_csv(index=False), "mca_readiness.csv", "text/csv")

mca = _frame(get_mca_results())
if mca.empty:
    error_message = get_prescriptive_error_message()
    if error_message:
        info_message(error_message)
    else:
        info_message("For the three-criterion assessment, connect sales, current stock and forecasts, then upload cleaned return/refund evidence with explicit coverage dates. Missing or unresolved criteria remain unavailable. Product costs and supplier lead times are not required for three-criterion MCA.")
    st.stop()

active_criteria, active_weights = _get_active_criteria_and_weights(mca, audit)

risk = _frame(get_risk_results())
recommendations = _frame(get_recommendation_results())
lookup = _product_lookup(recommendations, risk)
approved_ranked = _approved_with_products(mca, lookup)

section_header(
    "Product Prioritization",
    "Ranks SKUs by overall business priority using a balanced evaluation of Sales Velocity, Forecast Demand, and Return Rates.",
)

left, right = st.columns((0.28, 0.72), gap="small", vertical_alignment="top")

with left:
    with st.container(border=True):
        _render_weights_panel(active_criteria, active_weights)

with right:
    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Top Priority Products</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Products with the highest overall MCA scores are prioritized first to optimize inventory capital allocation.</p>',
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Product Prioritization Ranking</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Review product rankings, priority level tiers (High, Medium, Low), and key drivers.</p>',
            unsafe_allow_html=True,
        )
        ranking = _ranking_table(approved_ranked)
        st.dataframe(
            ranking,
            hide_index=True,
            width="stretch",
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "MCA Score": st.column_config.NumberColumn("MCA Score", format="%.3f"),
            },
        )

    with st.container(border=True):
        st.markdown('<p class="priority-card-title">Priority Detail Breakdown</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="priority-card-copy">Select an SKU to inspect its individual criteria values and weighted score contributions.</p>',
            unsafe_allow_html=True,
        )
        _render_details(approved_ranked, active_criteria, active_weights)

with st.expander("Approved Normalized Matrix & Alternative Scenarios", expanded=False):
    st.markdown("#### Full Normalized MCA Matrix")
    st.dataframe(mca, hide_index=True, width="stretch")
    st.download_button("Download MCA rankings", mca.to_csv(index=False), "mca_rankings.csv", "text/csv")

    st.markdown("#### Approved Criteria Weights")
    st.dataframe(
        pd.DataFrame(
            [
                {"Criterion": criterion, "Weight": float(active_weights.get(criterion, 0.0))}
                for criterion in active_criteria
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={"Weight": st.column_config.NumberColumn("Weight", format="%.3f")},
    )

    comparison = st.session_state.get("mca_sensitivity")
    if is_three and comparison is not None:
        st.markdown("#### Weight Sensitivity Scenarios")
        st.dataframe(comparison, hide_index=True)
        st.download_button("Download weight comparison", comparison.to_csv(index=False), "mca_weight_comparison.csv", "text/csv")
