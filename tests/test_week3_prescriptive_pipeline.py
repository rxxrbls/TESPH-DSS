import numpy as np
import pandas as pd
import pytest

from methodology_config import (
    FORECAST_HORIZON,
    MCA_CRITERIA,
    MCA_DIRECTIONS,
    MCA_WEIGHTS,
    REPLENISHMENT_CONFIG,
    STOCK_RISK_THRESHOLDS,
)
from prescriptive_calculations import (
    calculate_mca_scores,
    calculate_replenishment_quantity,
    calculate_safety_stock,
    calculate_stock_out_risk,
    calculate_target_stock_level,
    min_max_normalize,
)
from prescriptive_pipeline import (
    build_sku_mapping_from_stock_upload,
    run_prescriptive_pipeline,
)


def _pipeline_inputs():
    transaction = pd.DataFrame(
        {
            "Order ID": ["O1", "O2"],
            "Order Status": ["Completed", "Completed"],
            "SKU Reference No.": ["OLD-A", "OLD-B"],
            "Product Name": ["Item A", "Item B"],
            "product_key": ["P1", "P2"],
            "final_base_product_name": ["Item A", "Item B"],
            "final_category": ["A", "B"],
            "order_date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "Quantity": [5, 10],
            "Total Buyer Payment": [500.0, 1000.0],
            "Returned quantity": [1, 0],
            "Deal Price": [100.0, 100.0],
            "is_completed": [True, True],
            "is_cancelled": [False, False],
            "is_returned": [False, False],
        }
    )
    analytics = {
        "sales_velocity": pd.DataFrame(
            {"Product Key": ["P1", "P2"], "Sales Velocity": [2.0, 10.0]}
        ),
        "product_performance": pd.DataFrame(
            {
                "Product Key": ["P1", "P2"],
                "Gross Revenue": [500.0, 1000.0],
                "Gross Demand": [5.0, 10.0],
                "Returned Quantity": [1.0, 0.0],
            }
        ),
    }
    dates = pd.date_range("2026-09-03", periods=FORECAST_HORIZON, freq="D")
    forecast = pd.DataFrame(
        [
            {
                "SKU": sku,
                "Product": product,
                "Category": category,
                "Time": date,
                "Forecast": demand,
            }
            for sku, product, category, demand in (
                ("SKU-A", "Item A", "A", 2.0),
                ("SKU-B", "Item B", "B", 10.0),
            )
            for date in dates
        ]
    )
    forecast_results = {"forecast_output": forecast}
    stock = pd.DataFrame(
        {
            "product_key": ["P1", "P2"],
            "SKU": ["SKU-A", "SKU-B"],
            "Stock": [0.0, 300.0],
            "stock_as_of": pd.to_datetime(["2026-09-09", "2026-09-09"]),
            "match_status": ["candidate", "candidate"],
            "mapping_review_required": [False, False],
            "stock_valid": [True, True],
        }
    )
    return transaction, analytics, forecast_results, stock


def _crosswalk_with_resolved_keys(stock):
    result = stock.copy()
    result["crosswalk_product_key"] = result["product_key"]
    result["product_key"] = pd.NA
    return result


def test_mca_configuration_normalization_weights_and_deterministic_ties():
    assert len(MCA_CRITERIA) == 6
    assert set(MCA_DIRECTIONS) == set(MCA_CRITERIA)
    assert set(MCA_WEIGHTS) == set(MCA_CRITERIA)
    assert sum(MCA_WEIGHTS.values()) == pytest.approx(1.0)
    assert min_max_normalize(30, 10, 30, "benefit") == 1.0
    assert min_max_normalize(30, 10, 30, "cost") == 0.0
    assert min_max_normalize(4, 4, 4, "benefit") == 0.5

    alternatives = pd.DataFrame(
        {
            "SKU": ["B", "A"],
            **{criterion: [1.0, 1.0] for criterion in MCA_CRITERIA},
        }
    )
    ranked = calculate_mca_scores(alternatives, identifier_columns=["SKU"])
    assert ranked["SKU"].tolist() == ["A", "B"]
    assert ranked["Priority Rank"].tolist() == [1, 2]
    assert ranked["Priority Level"].tolist() == ["Medium", "Medium"]


def test_stock_risk_doi_index_and_default_classification_bands():
    forecasts = pd.DataFrame({"SKU": list("ABCDEF"), "Forecast": [70, 70, 70, 70, 70, 0]})
    inventory = pd.DataFrame(
        {"SKU": list("ABCDE"), "Current Stock": [0, 10, 30, 70, 80]}
    )
    risk = calculate_stock_out_risk(
        forecasts, inventory, item_columns=["SKU"], forecast_horizon_days=7
    ).set_index("SKU")
    assert risk.loc["A", "Days of Inventory"] == 0
    assert risk.loc["A", "Risk Index"] == 1
    assert risk.loc["A", "Stock-Out Risk"] == "Critical"
    assert risk.loc["B", "Stock-Out Risk"] == "Critical"
    assert risk.loc["C", "Stock-Out Risk"] == "High"
    assert risk.loc["D", "Stock-Out Risk"] == "Medium"
    assert risk.loc["E", "Stock-Out Risk"] == "Low"
    assert risk.loc["F", "Stock-Out Risk"] == "No Forecast Demand"
    assert STOCK_RISK_THRESHOLDS.critical_max_days == 1
    assert STOCK_RISK_THRESHOLDS.high_max_days == 3
    assert STOCK_RISK_THRESHOLDS.medium_max_days == 7


def test_target_stock_safety_stock_and_quantity():
    REPLENISHMENT_CONFIG.validate()
    assert calculate_safety_stock(70, forecast_horizon_days=7) == 10
    assert calculate_target_stock_level(70, forecast_horizon_days=7) == 150
    assert calculate_replenishment_quantity(150, 40) == 110
    assert calculate_replenishment_quantity(150, 151) == 0


def test_complete_shared_analytics_forecast_risk_mca_recommendation_flow():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    results = run_prescriptive_pipeline(
        transactions, analytics, forecast, stock, as_of="2026-09-28"
    )
    risk = results["risk_results"].set_index("SKU")
    mca = results["mca_results"].set_index("SKU")
    recommendations = results["recommendation_results"].set_index("SKU")

    assert risk.loc["SKU-A", "Stock-Out Risk"] == "Critical"
    assert risk.loc["SKU-A", "Risk Index"] == 1.0
    assert mca.loc["SKU-A", "Priority Rank"] in {1, 2}
    assert recommendations.loc["SKU-A", "Recommended Quantity"] == 30
    assert recommendations.loc["SKU-A", "Recommendation"] == "Replenish to target"
    assert recommendations.loc["SKU-A", "Recommendation Priority"] == "Immediate"
    assert recommendations.loc["SKU-B", "Recommended Quantity"] == 0
    assert recommendations.loc["SKU-B", "Recommendation"] == "Maintain stock"
    explanation = recommendations.loc["SKU-A", "Recommendation Explanation"]
    assert "Risk Index" in explanation
    assert "MCA" in explanation
    assert "14 lead/review days" in explanation


def test_stock_upload_mapping_uses_the_resolved_crosswalk_key():
    transactions, _, _, stock = _pipeline_inputs()
    transactions["SKU Reference No."] = ["SKU-A", "SKU-B"]
    crosswalk = _crosswalk_with_resolved_keys(stock)

    mapping, _ = build_sku_mapping_from_stock_upload(
        transactions,
        crosswalk,
        stock_as_of="2026-09-09",
        as_of="2026-09-28",
    )

    assert mapping.set_index("SKU").loc["SKU-A", "product_key"] == "P1"
    assert mapping["active"].all()


def test_prescriptive_risk_uses_the_resolved_crosswalk_key():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    crosswalk = _crosswalk_with_resolved_keys(stock)

    result = run_prescriptive_pipeline(
        transactions, analytics, forecast, crosswalk, as_of="2026-09-28"
    )
    risk = result["risk_results"].set_index("SKU")

    assert risk.loc["SKU-A", "Current Stock"] == 0
    assert risk.loc["SKU-A", "Stock-Out Risk"] == "Critical"


def test_missing_or_insufficient_inputs_are_not_silently_scored():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    with pytest.raises(ValueError, match="No eligible SKU forecast"):
        run_prescriptive_pipeline(
            transactions, analytics, {"forecast_output": pd.DataFrame()}, stock
        )
    partial = forecast["forecast_output"].iloc[:-1]
    with pytest.raises(ValueError, match="exactly 7 consecutive"):
        run_prescriptive_pipeline(
            transactions, analytics, {"forecast_output": partial}, stock
        )
    with pytest.raises(ValueError, match="missing:.*stock_valid"):
        run_prescriptive_pipeline(
            transactions, analytics, forecast, stock.drop(columns="stock_valid")
        )


def test_stale_or_review_required_inventory_is_excluded():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    stock.loc[0, "stock_as_of"] = pd.Timestamp("2026-01-01")
    stock.loc[1, "mapping_review_required"] = True
    result = run_prescriptive_pipeline(
        transactions, analytics, forecast, stock, as_of="2026-09-28"
    )
    risk = result["risk_results"].set_index("SKU")
    assert risk.loc["SKU-A", "Stock-Out Risk"] == "Insufficient Stock Data"
    assert risk.loc["SKU-B", "Stock-Out Risk"] == "Insufficient Stock Data"
    assert result["recommendation_results"].empty


def test_missing_mca_criterion_is_not_imputed():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    analytics["product_performance"].loc[0, "Returned Quantity"] = np.nan

    result = run_prescriptive_pipeline(
        transactions, analytics, forecast, stock, as_of="2026-09-28"
    )
    recommendation = result["recommendation_results"].set_index("SKU")

    assert "SKU-A" not in set(result["mca_results"]["SKU"])
    assert pd.isna(recommendation.loc["SKU-A", "Priority Level"])
    assert "MCA unavailable" in recommendation.loc[
        "SKU-A", "Recommendation Explanation"
    ]


def test_missing_stock_is_not_imputed_or_recommended():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    stock = stock.loc[stock["SKU"].ne("SKU-A")].copy()

    result = run_prescriptive_pipeline(
        transactions, analytics, forecast, stock, as_of="2026-09-28"
    )
    risk = result["risk_results"].set_index("SKU")

    assert risk.loc["SKU-A", "Stock-Out Risk"] == "Insufficient Stock Data"
    assert "SKU-A" not in set(result["recommendation_results"]["SKU"])


def test_unmatched_stock_is_not_used_for_risk_or_replenishment():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    stock.loc[0, "match_status"] = "unmatched"

    result = run_prescriptive_pipeline(
        transactions, analytics, forecast, stock, as_of="2026-09-28"
    )
    risk = result["risk_results"].set_index("SKU")

    assert risk.loc["SKU-A", "Stock-Out Risk"] == "Insufficient Stock Data"
    assert "SKU-A" not in set(result["recommendation_results"]["SKU"])


def test_zero_forecast_demand_needs_no_replenishment():
    transactions, analytics, forecast, stock = _pipeline_inputs()
    forecast["forecast_output"].loc[
        forecast["forecast_output"]["SKU"].eq("SKU-A"), "Forecast"
    ] = 0.0

    result = run_prescriptive_pipeline(
        transactions, analytics, forecast, stock, as_of="2026-09-28"
    )
    risk = result["risk_results"].set_index("SKU")
    recommendation = result["recommendation_results"].set_index("SKU")

    assert risk.loc["SKU-A", "Stock-Out Risk"] == "No Forecast Demand"
    assert risk.loc["SKU-A", "Risk Index"] == 0.0
    assert recommendation.loc["SKU-A", "Target Stock Level"] == 0
    assert recommendation.loc["SKU-A", "Recommended Quantity"] == 0
    assert recommendation.loc["SKU-A", "Recommendation"] == "Monitor; no forecast demand"
    assert "DOI not applicable" in recommendation.loc[
        "SKU-A", "Recommendation Explanation"
    ]