import pandas as pd

from src.prescriptive.mca import rank_skus


# KAN-267 - VALIDATE PRODUCT PRIORITY RANKING


def test_products_ranked_highest_to_lowest():
    df = pd.DataFrame({
        "sku": [
            "SKU-A",
            "SKU-B",
            "SKU-C",
            "SKU-D",
        ],
        "SKU Priority Score": [
            0.55,
            0.85,
            0.30,
            0.70,
        ],
    })

    ranked = rank_skus(df, identifier_columns=["sku"])

    assert ranked.iloc[0]["sku"] == "SKU-B"
    assert ranked.iloc[1]["sku"] == "SKU-D"
    assert ranked.iloc[2]["sku"] == "SKU-A"
    assert ranked.iloc[3]["sku"] == "SKU-C"


def test_highest_score_gets_rank_one():
    df = pd.DataFrame({
        "sku": ["SKU-A", "SKU-B", "SKU-C"],
        "SKU Priority Score": [0.40, 0.90, 0.60],
    })

    ranked = rank_skus(df, identifier_columns=["sku"])

    assert ranked.iloc[0]["sku"] == "SKU-B"
    assert ranked.iloc[0]["Priority Rank"] == 1


def test_rank_numbers_follow_score_order():
    df = pd.DataFrame({
        "sku": ["SKU-A", "SKU-B", "SKU-C"],
        "SKU Priority Score": [0.70, 0.90, 0.50],
    })

    ranked = rank_skus(df, identifier_columns=["sku"])

    assert list(ranked["Priority Rank"]) == [1, 2, 3]
    assert list(ranked["SKU Priority Score"]) == [
        0.90,
        0.70,
        0.50,
    ]


def test_original_scores_are_preserved():
    df = pd.DataFrame({
        "sku": ["SKU-A", "SKU-B"],
        "SKU Priority Score": [0.65, 0.80],
    })

    ranked = rank_skus(df, identifier_columns=["sku"])

    assert ranked.iloc[0]["SKU Priority Score"] == 0.80
    assert ranked.iloc[1]["SKU Priority Score"] == 0.65