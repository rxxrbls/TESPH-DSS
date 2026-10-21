"""Integration adapter shared by upload callbacks and backend sales ingestion."""
from pathlib import Path

import pandas as pd

from etl_config import RUNTIME_DB_PATH
import prescriptive_pipeline
from return_refund_store import load_evidence, refresh_batch, invalidate_outputs
from three_criterion_mca import Coverage, CRITERIA, evaluate_requests


def review_path(transaction_db=RUNTIME_DB_PATH):
    return Path(transaction_db).with_name(Path(transaction_db).stem + "_return_review.db")


def refresh_connected(transactions, analytics, forecasts, stock, *, snapshot=None,
                      coverage=None, batch_type="stock", store_path=None, **kwargs):
    path = review_path() if store_path is None else Path(store_path)
    existing = load_evidence(path)
    if existing is None and coverage is None:
        # Compatibility for the previously approved five-criterion pipeline.
        return prescriptive_pipeline.run_prescriptive_pipeline(transactions, analytics, forecasts, stock, **kwargs)
    def calculate(records, policy):
        config = Coverage(**policy)
        return prescriptive_pipeline.run_prescriptive_pipeline(
            transactions, analytics, forecasts, stock, mca_return_snapshot=records,
            mca_coverage=config, mca_period_start=config.order_start,
            mca_period_end=config.order_end, **kwargs)
    return refresh_batch(path, batch_type=batch_type, snapshot=snapshot,
                         coverage=coverage, calculate=calculate)


def review_after_sales(transactions, transaction_db=RUNTIME_DB_PATH):
    """Recheck persisted requests after every accepted sales batch.

    Sales changes invalidate the stock crosswalk. Publish review with unavailable
    dependent rankings until stock is connected again, never stale prior scores.
    """
    path = review_path(transaction_db)
    if load_evidence(path) is None:
        return
    invalidate_outputs(path)
    from active_inventory import build_active_mapping
    mapping, _ = build_active_mapping(transactions)
    mapping = mapping.loc[mapping["SKU"].notna(), ["product_key", "SKU"]]
    def calculate(records, policy):
        audit, review = evaluate_requests(transactions, records, mapping, Coverage(**policy))
        audit["MCA Status"] = "Unavailable: refresh connected stock outputs after sales batch"
        return {"return_request_review": review, "mca_audit": audit,
                "mca_results": pd.DataFrame(columns=["SKU", *CRITERIA]),
                "recommendation_results": pd.DataFrame(),
                "risk_results": pd.DataFrame()}
    refresh_batch(path, batch_type="sales", calculate=calculate)
