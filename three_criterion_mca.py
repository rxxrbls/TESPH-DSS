"""Conditionally approved three-criterion MCA; all rankings are provisional.

No financial amounts or physical-return assumptions enter this quantity rate.
Coverage describes selected request dates, not lifetime returns for an order.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

import numpy as np
import pandas as pd

from analytics_calculations import prepare_transactions
from prescriptive_calculations import calculate_mca_scores

RATE = "Recorded Return/Refund Quantity Rate"
CRITERIA = ("Sales Velocity", "Forecasted Demand", RATE)
DIRECTIONS = dict(zip(CRITERIA, ("benefit", "benefit", "cost")))
SCENARIOS = {
    "equal_thirds": dict(zip(CRITERIA, (1 / 3, 1 / 3, 1 / 3))),
    "volume_quality": dict(zip(CRITERIA, (.25, .25, .5))),
}
POLICY_VERSION = "three-criterion-provisional-v1"
IDENTITY = ["Order ID", "Product Name", "Variation Name"]
REQUIRED = [
    "Return ID", *IDENTITY, "product_key", "Return Creation Time",
    "Return / Refund Status", "Return Quantity", "Return/Refund Solution",
    "Refund Completed Time",
]


@dataclass(frozen=True)
class Coverage:
    order_start: str
    order_end: str
    request_start: str
    request_end: str
    export_start: str
    export_end: str
    established: bool = False
    timezone: str = "unspecified"

    def validate(self):
        for start, end in ((self.order_start, self.order_end),
                           (self.request_start, self.request_end),
                           (self.export_start, self.export_end)):
            if pd.isna(pd.Timestamp(start)) or pd.isna(pd.Timestamp(end)) or pd.Timestamp(start) > pd.Timestamp(end):
                raise ValueError("Coverage dates must be valid and ordered")
        if not isinstance(self.established, bool):
            raise ValueError("Coverage confirmation must be boolean")
        if pd.Timestamp(self.request_start) > pd.Timestamp(self.order_start) or pd.Timestamp(self.request_end) < pd.Timestamp(self.order_end):
            raise ValueError("Selected request coverage must contain the order-date window")


def fingerprint(frame):
    """Order-independent fingerprint including columns and all supplied fields."""
    canonical = frame.fillna("").astype(str)
    rows = sorted(json.dumps(row, ensure_ascii=False) for row in canonical.to_numpy().tolist())
    return hashlib.sha256(json.dumps([list(frame.columns), rows], ensure_ascii=False).encode()).hexdigest()


def validate_snapshot(snapshot):
    missing = set(REQUIRED) - set(snapshot.columns)
    if missing:
        raise ValueError("Return/refund input missing: " + ", ".join(sorted(missing)))
    result = snapshot.copy().fillna("")
    for name in ["Return ID", *IDENTITY, "product_key", "Return / Refund Status", "Return/Refund Solution"]:
        result[name] = result[name].astype(str).str.strip()
    if result[["Return ID", "Order ID", "Product Name", "product_key"]].eq("").any().any():
        raise ValueError("Return/request and product identifiers must be supplied")
    # Identical repeated rows can be safely collapsed; conflicting lines cannot.
    result = result.drop_duplicates()
    if result.duplicated(["Return ID", "product_key"]).any():
        raise ValueError("Conflicting or ambiguous lines for the same Return ID/product")
    return result.reset_index(drop=True)


def evaluate_requests(transactions, snapshot, mapping, coverage):
    """Match request lines to exact sales identities and audit every decision."""
    coverage.validate()
    records = validate_snapshot(snapshot)
    if "SKU" in records:
        records = records.rename(columns={"SKU": "Source SKU"})
    prepared = prepare_transactions(transactions)
    sales = transactions[IDENTITY + ["product_key"]].copy().reset_index(drop=True)
    for column in IDENTITY + ["product_key"]:
        sales[column] = sales[column].fillna("").astype(str).str.strip()
    sales["order_date"] = prepared["Time"]
    sales["demand"] = prepared["Gross Demand"]
    sales["in_period"] = sales["order_date"].dt.normalize().between(
        pd.Timestamp(coverage.order_start), pd.Timestamp(coverage.order_end))
    # Multiple identical source identities are aggregated, not multiplied in a join.
    grouped = sales.groupby(IDENTITY + ["product_key"], as_index=False, dropna=False).agg(
        ordered_units=("demand", "sum"), in_period=("in_period", "all"),
        order_date=("order_date", "min"))
    if grouped.duplicated(IDENTITY).any():
        raise ValueError("Sales identity maps to multiple product keys")
    mapping = mapping[["product_key", "SKU"]].copy()
    if mapping.isna().any().any() or mapping.duplicated("product_key").any() or mapping.duplicated("SKU").any():
        raise ValueError("MCA mapping must be unique and complete")
    matched = records.merge(grouped, on=IDENTITY + ["product_key"], how="left", validate="many_to_one")
    matched = matched.merge(mapping, on="product_key", how="left", validate="many_to_one")
    matched["Review Decision"] = "Excluded"
    matched["Review Reason"] = "Outside assessment order/request dates"
    request_date = pd.to_datetime(matched["Return Creation Time"], errors="coerce")
    in_request = request_date.dt.normalize().between(
        pd.Timestamp(coverage.request_start), pd.Timestamp(coverage.request_end))
    in_scope = matched["in_period"].fillna(False).astype(bool) & in_request
    qty = pd.to_numeric(matched["Return Quantity"], errors="coerce")
    matched["Recorded Units"] = qty
    unknown_match = matched["ordered_units"].isna()
    invalid_date = request_date.isna()
    unresolved = in_scope & ~matched["Return / Refund Status"].isin(
        ["Request Refunded", "Request Cancelled", "Request Rejected"])
    matched.loc[in_scope, ["Review Decision", "Review Reason"]] = ["Not counted", "Cancelled/rejected request"]
    refunded = in_scope & matched["Return / Refund Status"].eq("Request Refunded")
    matched.loc[refunded, ["Review Decision", "Review Reason"]] = ["Counted", "Recorded Request Refunded outcome"]
    bad_quantity = in_scope & (~np.isfinite(qty) | qty.le(0) | qty.mod(1).ne(0))
    bad_solution = refunded & ~matched["Return/Refund Solution"].isin(["Refund Only", "Return Refund", "Return and Refund"])
    excess = refunded & qty.gt(matched["ordered_units"])
    no_demand = refunded & matched["ordered_units"].le(0)
    # Multiple potentially effective requests are not automatically added together.
    effective = in_scope & ~matched["Return / Refund Status"].isin(["Request Cancelled", "Request Rejected"])
    repeated = matched.loc[effective].groupby(["Order ID", "product_key"])["Return ID"].transform("nunique").gt(1)
    for mask, reason in [
        (unknown_match, "No exact matching sales item"),
        (invalid_date, "Invalid request creation date"),
        (unresolved, "Unresolved source status/dispute"),
        (bad_quantity, "Invalid recorded quantity"),
        (bad_solution, "Unsupported refund solution"),
        (excess | no_demand, "Recorded units exceed eligible ordered units"),
        (matched.index.isin(repeated.index[repeated]), "Ambiguous repeated effective requests"),
    ]:
        matched.loc[mask, ["Review Decision", "Review Reason"]] = ["Unresolved", reason]
    # Inconsistent request-level outcomes across item lines require review.
    conflict = matched.groupby("Return ID")["Return / Refund Status"].transform("nunique").gt(1)
    matched.loc[conflict, ["Review Decision", "Review Reason"]] = ["Unresolved", "Conflicting request-level statuses"]
    matched["Missing Completion Date"] = (
        matched["Return / Refund Status"].eq("Request Refunded")
        & matched["Refund Completed Time"].astype(str).str.strip().eq(""))
    denominator = sales.loc[sales["in_period"]].groupby("product_key")["demand"].sum()
    audit = mapping.copy()
    audit["Eligible Ordered Units"] = audit["product_key"].map(denominator).fillna(0)
    counted = matched.loc[matched["Review Decision"].eq("Counted")].groupby("product_key")["Recorded Units"].sum()
    audit["Recorded Refunded Units"] = audit["product_key"].map(counted).fillna(0)
    flagged = set(matched.loc[matched["Review Decision"].eq("Unresolved"), "product_key"])
    # Unknown product mappings may hide a relevant SKU: block the whole population.
    global_unknown = bool((unknown_match & matched["SKU"].isna()).any())
    audit["Return Coverage Established"] = coverage.established
    audit["Return Review Status"] = "Ready within selected request-date coverage"
    audit.loc[audit["Eligible Ordered Units"].le(0), "Return Review Status"] = "Unavailable: no eligible ordered units"
    audit.loc[audit["product_key"].isin(flagged), "Return Review Status"] = "Unavailable: unresolved request evidence"
    if not coverage.established or global_unknown:
        audit["Return Review Status"] = "Unavailable: coverage or unmatched product evidence"
    eligible = audit["Return Review Status"].str.startswith("Ready")
    audit[RATE] = np.nan
    audit.loc[eligible, RATE] = 100 * (audit.loc[eligible, "Recorded Refunded Units"] / audit.loc[eligible, "Eligible Ordered Units"])
    if audit[RATE].dropna().gt(100).any():
        bad = audit[RATE].gt(100)
        audit.loc[bad, RATE] = np.nan
        audit.loc[bad, "Return Review Status"] = "Unavailable: aggregate recorded units exceed ordered units"
    return audit, matched


def rank_scenarios(criteria):
    results = {}
    finite = criteria[list(CRITERIA)].apply(pd.to_numeric, errors="coerce").apply(np.isfinite).all(axis=1)
    eligible = criteria.loc[finite, ["SKU", *CRITERIA]]
    for name, weights in SCENARIOS.items():
        results[name] = calculate_mca_scores(eligible, identifier_columns=["SKU"],
            criteria=CRITERIA, weights=weights, directions=DIRECTIONS)
        results[name]["Weight Scenario"] = name
        results[name]["Approval Status"] = ("TA-approved equal-weight baseline; final validation pending"
            if name == "equal_thirds" else "Sensitivity comparison only; not the approved baseline")
    a = results["equal_thirds"]
    b = results["volume_quality"]
    comparison = a[["SKU", "Priority Rank", "Priority Level"]].merge(
        b[["SKU", "Priority Rank", "Priority Level"]], on="SKU", suffixes=(" Equal", " Quality"))
    comparison["Rank Change"] = comparison["Priority Rank Quality"] - comparison["Priority Rank Equal"]
    comparison["Group Changed"] = comparison["Priority Level Equal"].ne(comparison["Priority Level Quality"])
    x, y = eligible["Sales Velocity"], eligible["Forecasted Demand"]
    variable = len(eligible) >= 2 and x.nunique() > 1 and y.nunique() > 1
    summary = {
        "eligible_skus": len(eligible), "excluded_skus": len(criteria) - len(eligible),
        "pearson": float(x.corr(y)) if variable else None,
        "spearman": float(x.rank().corr(y.rank())) if variable else None,
        "correlation_status": "Computed; threshold requires TA interpretation" if variable else "Undefined: insufficient rows or constant criterion",
        "rank_changes": int(comparison["Rank Change"].ne(0).sum()),
        "group_changes": int(comparison["Group Changed"].sum()),
        "max_absolute_rank_change": int(comparison["Rank Change"].abs().max()) if len(comparison) else 0,
        "policy_version": POLICY_VERSION,
        "final_weights_locked": True,
        "approved_baseline": "equal_thirds",
        "final_validation_pending": True,
        "criterion_unique_values": {c: int(eligible[c].nunique()) for c in CRITERIA},
        "criterion_minimums": {c: float(eligible[c].min()) if len(eligible) else None for c in CRITERIA},
        "criterion_maximums": {c: float(eligible[c].max()) if len(eligible) else None for c in CRITERIA},
    }
    return results, comparison, summary
