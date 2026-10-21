"""Regression contracts for performance fixes: identical keys and missing counts."""
import numpy as np
import pandas as pd
import pytest

from etl import count_missing_values, detect_missing_values
from final_etl_handoff import frame_keys, stable_hash, SHIPPING_FIELDS, PAYMENT_FIELDS


@pytest.mark.parametrize("data", [
    {"a": [" a  b", None, "<NA>", "x\ny"], "b": [1., np.nan, -2.5, 0.]},
    {"a": [1, 2], "b": [1.5, 3.]},
    {"a": pd.Series(["a", None], dtype="string"), "b": pd.Series(["", "2"], dtype="string")},
    {"a": pd.to_datetime(["2026-01-01", None])},
])
def test_optimized_hashes_match_original_row_apply(data):
    frame = pd.DataFrame(data)
    expected = frame.apply(lambda row: stable_hash("test_", row.tolist()), axis=1)
    pd.testing.assert_series_equal(frame_keys(frame, list(frame), "test_"), expected)


def test_missing_count_equals_full_location_report():
    frame = pd.DataFrame({"a": [None, "", " \t", "literal", "<NA>"], "b": [0, np.nan, -1, 2, 3],
                          "c": pd.Series([pd.NA, " ", "x", "", "0"], dtype="string")})
    assert count_missing_values(frame) == len(detect_missing_values(frame)) == 7


def test_actual_source_hashes_match_original_on_representative_rows():
    from etl import load_prepared_transactions
    frame = load_prepared_transactions().iloc[::227]
    for columns, prefix in [(SHIPPING_FIELDS, "shp_"), (PAYMENT_FIELDS, "pay_"),
                             (["Order ID", "product_key", "source_file", "Order Creation Date", "Quantity", "Deal Price", "Grand Total"], "line_")]:
        expected = frame[columns].apply(lambda row: stable_hash(prefix, row.tolist()), axis=1)
        pd.testing.assert_series_equal(frame_keys(frame, columns, prefix), expected)


def test_streamed_fingerprints_preserve_original_payload_bytes():
    from hashlib import sha256
    from runtime_data_store import _fingerprints, _normalized_column
    frame = pd.DataFrame({"Order ID": ["0001", "2", None], "Quantity": [1., -2., np.nan],
                          "Order Creation Date": ["2026-01-01", "-", None]})
    columns = list(frame)
    normalized = [_normalized_column(frame[column], column).tolist() for column in columns]
    expected = pd.Series([sha256("\x1f".join(map(str, row)).encode()).hexdigest() for row in zip(*normalized)], dtype="string")
    pd.testing.assert_series_equal(_fingerprints(frame, columns), expected)
