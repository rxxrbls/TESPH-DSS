"""Deterministic active-catalog evidence; never manufacture missing source SKUs."""

from pathlib import Path

import numpy as np
import pandas as pd

from analytics_calculations import _clean_text, _require_columns, prepare_transactions
from methodology_config import REPLENISHMENT_CONFIG


INVENTORY_PATH = Path(__file__).resolve().parent / "raw_data/current_stock/current_stock_inventory_2026-09-09.csv"


def build_active_mapping(transactions: pd.DataFrame, inventory: pd.DataFrame | None = None,
                         *, as_of: str | pd.Timestamp | None = None,
                         max_age_days: int = REPLENISHMENT_CONFIG.max_stock_age_days):
    """Presence in a fresh current catalog establishes activity, not client approval.

    Only unique exact product-key matches with real, non-reused seller SKUs are
    admitted. Zero stock does not imply inactivity. All other rows get reasons.
    """
    if max_age_days < 0:
        raise ValueError("max_age_days must be nonnegative")
    inventory = pd.read_csv(INVENTORY_PATH, dtype="string") if inventory is None else inventory.copy()
    _require_columns(inventory, ["product_key", "SKU", "Stock As-Of Date", "Current Stock"])
    inventory["product_key"] = _clean_text(inventory["product_key"])
    inventory["SKU"] = _clean_text(inventory["SKU"])
    frame = prepare_transactions(transactions)
    base = frame[["Product Key", "Product", "Category"]].drop_duplicates().rename(columns={"Product Key": "product_key"})
    if base["product_key"].duplicated().any():
        raise ValueError("Historical product keys have conflicting product/category metadata")
    # Keep Python sets: Arrow-backed groupby aggregation can coerce sets to lists.
    sources = {key: set(group["SKU"].dropna()) for key, group in frame.groupby("Product Key")}
    today = pd.Timestamp(as_of).normalize() if as_of is not None else pd.Timestamp.today().normalize()
    if pd.isna(today):
        raise ValueError("as_of must be a valid date")
    dates = pd.to_datetime(inventory["Stock As-Of Date"], errors="coerce")
    age = (today - dates).dt.days
    stock = pd.to_numeric(inventory["Current Stock"], errors="coerce")
    inventory["Reason"] = np.select([
        inventory["SKU"].isna(), inventory["SKU"].duplicated(False),
        inventory["product_key"].isna() | inventory["product_key"].duplicated(False),
        ~inventory["product_key"].isin(base["product_key"]),
        dates.isna() | age.lt(0) | age.gt(max_age_days),
        ~np.isfinite(stock.astype(float)) | stock.lt(0),
    ], ["Missing source SKU", "Reused SKU: stock pool unresolved", "Missing or duplicate product key",
        "No exact historical match", "Missing, future, or stale catalog date", "Invalid current stock"], default="Eligible current catalog match")
    for idx, row in inventory.loc[inventory["Reason"].eq("Eligible current catalog match")].iterrows():
        source_skus = sources.get(row["product_key"], set())
        if source_skus and source_skus != {row["SKU"]}:
            inventory.loc[idx, "Reason"] = "Historical/current SKU conflict"
    # An explicit source status overrides presence in the current catalog.
    for flag in ("active", "category_active"):
        if flag in inventory:
            values = inventory[flag].astype("string").str.strip().str.lower()
            if not values.isin(["true", "false", "1", "0"]).all():
                raise ValueError(f"Inventory {flag} must explicitly contain true/false or 1/0")
            inventory.loc[~values.isin(["true", "1"]), "Reason"] = f"Inactive catalog {flag}"
    accepted_columns = ["product_key", "SKU", "Stock As-Of Date"]
    if "Supplier Lead Time" in inventory.columns:
        accepted_columns.append("Supplier Lead Time")
    accepted = inventory.loc[
        inventory["Reason"].eq("Eligible current catalog match"), accepted_columns
    ]
    mapping = base.merge(accepted, on="product_key", how="left", validate="one_to_one")
    mapping["active"] = mapping["SKU"].notna()
    active_categories = set(mapping.loc[mapping["active"], "Category"])
    mapping["category_active"] = mapping["Category"].isin(active_categories)
    mapping["client_approved"] = False
    mapping["catalog_active"] = mapping["active"]
    mapping["Eligibility Basis"] = np.where(mapping["active"], "Exact current-catalog match (team rule)", "No eligible current-catalog match")
    return mapping, inventory
