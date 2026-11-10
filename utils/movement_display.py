"""Pure row selection helpers for product movement tables."""

import pandas as pd


def movement_table_views(display: pd.DataFrame, preview_limit: int = 12) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the unchanged preview rows and complete view from one prepared frame."""
    if preview_limit < 0:
        raise ValueError("preview_limit cannot be negative")
    return display.head(preview_limit).copy(), display.copy()
