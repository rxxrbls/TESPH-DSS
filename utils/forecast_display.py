"""Presentation of authoritative SKU backtests; never substitute missing scores."""

import numpy as np
import pandas as pd
import streamlit as st


def format_metric(value) -> str:
    if pd.isna(value):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not np.isfinite(number):
        return "N/A"
    if number == 0:
        return "0.00"
    return f"{number:.4e}" if abs(number) < 0.005 else f"{number:.4f}"


def accuracy_table(metrics: pd.DataFrame, best: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    """One row per SKU/method, with no averaging of unrelated SKU scores."""
    result = metrics.copy()
    for column in ("MAE", "RMSE", "MAPE", "Raw MAPE", "R2"):
        if column not in result:
            result[column] = np.nan
        result[column] = result[column].map(format_metric)
    adjusted = ("MAPE Status" in result and result["MAPE Status"].str.startswith("Adjusted", na=False).all())
    result = result.rename(columns={"MAPE": "Adjusted MAPE (%)" if adjusted else "MAPE (%)", "Raw MAPE": "Raw MAPE (%)", "R2": "R²"})
    winners = set(zip(best.get("SKU", []), best.get("Method", [])))
    reasons, statuses = [], []
    for _, row in result.iterrows():
        sku, method = row.get("SKU"), row.get("Method")
        statuses.append("Selected" if (sku, method) in winners else "Not selected" if winners else "Selection unavailable")
        observations = detail.loc[detail["SKU"].eq(sku) & detail["Method"].eq(method)] if {"SKU", "Method", "Actual"}.issubset(detail.columns) else pd.DataFrame()
        if row["R²"] != "N/A":
            reasons.append("Defined")
        elif observations.empty:
            reasons.append("N/A: validation unavailable")
        elif len(observations) < 2:
            reasons.append("N/A: fewer than two observations")
        elif observations["Actual"].nunique() == 1:
            reasons.append("N/A: constant actual demand")
        else:
            reasons.append("N/A: missing or invalid score")
    result["R² Status"] = reasons
    result["Selection"] = statuses
    return result


def render_forecast_accuracy(results: dict) -> None:
    st.subheader("Forecast Method Accuracy")
    st.caption("Lower MAE / RMSE / MAPE and higher R² are better. Scores compare held-out actual demand with predictions, separately for each SKU. Small nonzero scores use scientific notation; N/A never means zero.")
    metrics = results.get("validation_metrics", pd.DataFrame())
    if metrics.empty:
        st.info("Validation metrics are unavailable. No accuracy score can be reported.")
        return
    detail = results.get("validation_detail", pd.DataFrame())
    best = results.get("best_methods", pd.DataFrame())
    table = accuracy_table(metrics, best, detail)
    st.dataframe(table, hide_index=True)
    if not detail.empty and "Actual" in detail and detail["Actual"].eq(0).all():
        st.warning("Every actual demand observation in this validation window is zero. Zero or near-zero errors describe this no-demand window; they do not establish accuracy during active sales. R² and raw MAPE are undefined for these observations.")
    elif not detail.empty and {"SKU", "Actual"}.issubset(detail.columns):
        sku_zero_mask = detail.groupby("SKU", sort=False)["Actual"].apply(lambda s: bool(s.eq(0).all()))
        zero_sku_count = int(sku_zero_mask.sum())
        total_sku_count = int(len(sku_zero_mask))
        if zero_sku_count > 0:
            active_sku_count = total_sku_count - zero_sku_count
            st.info(
                f"Holdout Demand Note: {zero_sku_count:,} of {total_sku_count:,} evaluated SKUs had 0 actual demand "
                f"across the rolling 14-day holdout validation window (dormant recent sales period), resulting in "
                f"`0.00` MAE/RMSE/Adjusted MAPE and `N/A: constant actual demand` for R². "
                f"The remaining {active_sku_count:,} SKUs had active holdout demand and non-zero validation errors."
            )
    st.caption("MAE and RMSE are in demand units. Percentage scores are already multiplied by 100. Adjusted MAPE uses the recorded denominator floor and retains zero-demand days; raw MAPE is undefined if any actual is zero. R² is undefined for constant actuals or fewer than two observations, including Linear Regression. Negative R² values are valid.")
    st.caption("Model selection uses unrounded MAPE, then RMSE, then method name for exact ties. All methods use the same rolling origins and horizon. Each origin/step has equal weight, so dates may repeat across origins. These are model-selection validation scores, not an independent final test set.")
    st.download_button("Download full-precision validation metrics", metrics.to_csv(index=False), "forecast_validation_metrics.csv", "text/csv")

    eligibility = results.get("eligibility", pd.DataFrame()) if isinstance(results, dict) else pd.DataFrame()
    inv_review = results.get("inventory_review", pd.DataFrame()) if isinstance(results, dict) else pd.DataFrame()
    if (isinstance(eligibility, pd.DataFrame) and not eligibility.empty) or (
        isinstance(inv_review, pd.DataFrame) and not inv_review.empty
    ):
        with st.expander("SKU Forecast Eligibility & Exclusion Audit"):
            lines = []
            if isinstance(eligibility, pd.DataFrame) and not eligibility.empty and "Eligible" in eligibility.columns:
                total_keys = len(eligibility)
                active_col = "active" if "active" in eligibility.columns else ("Active SKU" if "Active SKU" in eligibility.columns else None)
                active_cnt = (
                    int(eligibility[active_col].fillna(False).astype(bool).sum())
                    if active_col is not None
                    else total_keys
                )
                eligible_cnt = int(eligibility["Eligible"].fillna(False).astype(bool).sum())
                excluded_cnt = max(0, active_cnt - eligible_cnt)
                lines.append(
                    f"- **Active Mapped SKUs Evaluated**: `{active_cnt:,}` active SKUs (out of `{total_keys:,}` historical product keys; "
                    f"`{eligible_cnt:,}` forecasted, `{excluded_cnt:,}` active SKUs excluded by minimum history requirement of 44 days = 37 training + 7 horizon)"
                )
                if "Reason" in eligibility.columns:
                    for reason, cnt in eligibility["Reason"].value_counts().items():
                        lines.append(f"  - *{reason}*: `{int(cnt):,}` SKUs")
            if isinstance(inv_review, pd.DataFrame) and not inv_review.empty and "Reason" in inv_review.columns:
                lines.append(f"- **Inventory Mapping & Exclusion Reasons** (`{len(inv_review):,}` stock rows audited):")
                for reason, cnt in inv_review["Reason"].value_counts().items():
                    lines.append(f"  - *{reason}*: `{int(cnt):,}` rows")
            if lines:
                st.markdown("\n".join(lines))
            if isinstance(eligibility, pd.DataFrame) and not eligibility.empty:
                st.download_button(
                    "Download SKU forecast eligibility audit (CSV)",
                    eligibility.to_csv(index=False),
                    "sku_forecast_eligibility_audit.csv",
                    "text/csv",
                )
    if not detail.empty:
        with st.expander("Actual vs. predicted validation"):
            sku = st.selectbox("Validation SKU", sorted(detail["SKU"].unique()))
            subset = detail.loc[detail["SKU"].eq(sku)]
            origin = st.selectbox("Training cutoff", sorted(subset["Origin"].unique()), format_func=lambda value: pd.Timestamp(value).strftime("%Y-%m-%d"))
            subset = subset.loc[subset["Origin"].eq(origin)]
            chart = subset.pivot(index="Time", columns="Method", values="Forecast")
            chart["Actual"] = subset.groupby("Time")["Actual"].first()
            st.line_chart(chart, x_label="Holdout date", y_label="Demand (units)")
            st.dataframe(subset, hide_index=True)
            st.download_button("Download all actual vs. predicted observations", detail.to_csv(index=False), "forecast_validation_detail.csv", "text/csv")
