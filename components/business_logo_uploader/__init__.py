"""Streamlit component for one-click circular business logo uploads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_COMPONENT = components.declare_component(
    "business_logo_uploader",
    path=str(Path(__file__).parent / "frontend"),
)


def business_logo_uploader(
    *,
    current_image: str,
    business_name: str,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Render the circular logo picker and return the selected file payload."""
    return _COMPONENT(
        currentImage=current_image,
        businessName=business_name,
        key=key,
        default=None,
    )
