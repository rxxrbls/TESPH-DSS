"""Outlined SVG icons library for TESPH-DSS.

Follows the professional outlined vector style in design references (Image 3):
- Minimalist, 2px stroke width, stroke-based vector graphics
- Standardized viewBox 0 0 24 24
- Consistent sizing, colors, and visual weights
- Zero emoji characters
"""

from __future__ import annotations


def icon_svg(
    name: str,
    size: int = 18,
    color: str = "currentColor",
    stroke_width: float = 2.0,
    extra_class: str = "",
) -> str:
    """Return inline SVG for an outlined icon."""
    paths = {
        "bell": (
            '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>'
            '<path d="M13.73 21a2 2 0 0 1-3.46 0"></path>'
        ),
        "user": (
            '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path>'
            '<circle cx="12" cy="7" r="4"></circle>'
        ),
        "user_round": (
            '<circle cx="12" cy="8" r="5"></circle>'
            '<path d="M20 21a8 8 0 0 0-16 0"></path>'
        ),
        "settings": (
            '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>'
            '<circle cx="12" cy="12" r="3"></circle>'
        ),
        "log_out": (
            '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>'
            '<polyline points="16 17 21 12 16 7"></polyline>'
            '<line x1="21" y1="12" x2="9" y2="12"></line>'
        ),
        "edit": (
            '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>'
            '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>'
        ),
        "pencil": (
            '<line x1="18" y1="2" x2="22" y2="6"></line>'
            '<path d="M7.5 20.5 19 9l-4-4L3.5 16.5 2 22z"></path>'
        ),
        "book_open": (
            '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>'
            '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>'
        ),
        "database": (
            '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>'
            '<path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>'
            '<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>'
        ),
        "info": (
            '<circle cx="12" cy="12" r="10"></circle>'
            '<line x1="12" y1="16" x2="12" y2="12"></line>'
            '<line x1="12" y1="8" x2="12.01" y2="8"></line>'
        ),
        "chevron_down": (
            '<polyline points="6 9 12 15 18 9"></polyline>'
        ),
        "chevron_right": (
            '<polyline points="9 18 15 12 9 6"></polyline>'
        ),
        "check_circle": (
            '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>'
            '<polyline points="22 4 12 14.01 9 11.01"></polyline>'
        ),
        "alert_triangle": (
            '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path>'
            '<line x1="12" y1="9" x2="12" y2="13"></line>'
            '<line x1="12" y1="17" x2="12.01" y2="17"></line>'
        ),
        "lock": (
            '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>'
            '<path d="M7 11V7a5 5 0 0 1 10 0v4"></path>'
        ),
        "mail": (
            '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>'
            '<polyline points="22,6 12,13 2,6"></polyline>'
        ),
        "monitor": (
            '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>'
            '<line x1="8" y1="21" x2="16" y2="21"></line>'
            '<line x1="12" y1="17" x2="12" y2="21"></line>'
        ),
        "download": (
            '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>'
            '<polyline points="7 10 12 15 17 10"></polyline>'
            '<line x1="12" y1="15" x2="12" y2="3"></line>'
        ),
        "upload_cloud": (
            '<polyline points="16 16 12 12 8 16"></polyline>'
            '<line x1="12" y1="12" x2="12" y2="21"></line>'
            '<path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"></path>'
            '<polyline points="16 16 12 12 8 16"></polyline>'
        ),
        "refresh_cw": (
            '<polyline points="23 4 23 10 17 10"></polyline>'
            '<polyline points="1 20 1 14 7 14"></polyline>'
            '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>'
        ),
        "shield": (
            '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>'
        ),
        "sun": (
            '<circle cx="12" cy="12" r="4"></circle>'
            '<path d="M12 2v2"></path>'
            '<path d="M12 20v2"></path>'
            '<path d="m4.93 4.93 1.41 1.41"></path>'
            '<path d="m17.66 17.66 1.41 1.41"></path>'
            '<path d="M2 12h2"></path>'
            '<path d="M20 12h2"></path>'
            '<path d="m6.34 17.66-1.41 1.41"></path>'
            '<path d="m19.07 4.93-1.41 1.41"></path>'
        ),
        "moon": (
            '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path>'
        ),
        "sliders_horizontal": (
            '<line x1="21" x2="14" y1="4" y2="4"></line>'
            '<line x1="10" x2="3" y1="4" y2="4"></line>'
            '<line x1="21" x2="12" y1="12" y2="12"></line>'
            '<line x1="8" x2="3" y1="12" y2="12"></line>'
            '<line x1="21" x2="16" y1="20" y2="20"></line>'
            '<line x1="12" x2="3" y1="20" y2="20"></line>'
            '<line x1="14" x2="14" y1="2" y2="6"></line>'
            '<line x1="8" x2="8" y1="10" y2="14"></line>'
            '<line x1="16" x2="16" y1="18" y2="22"></line>'
        ),
        "layout": (
            '<rect width="18" height="18" x="3" y="3" rx="2"></rect>'
            '<path d="M12 3v18"></path>'
        ),
        "file_text": (
            '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"></path>'
            '<path d="M14 2v4a2 2 0 0 0 2 2h4"></path>'
            '<path d="M10 9H8"></path>'
            '<path d="M16 13H8"></path>'
            '<path d="M16 17H8"></path>'
        ),
        "external_link": (
            '<path d="M15 3h6v6"></path>'
            '<path d="M10 14 21 3"></path>'
            '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>'
        ),
        "x": (
            '<path d="M18 6 6 18"></path>'
            '<path d="M6 6l12 12"></path>'
        ),
        "arrow_right": (
            '<path d="M5 12h14"></path>'
            '<path d="m12 5 7 7-7 7"></path>'
        ),
    }

    body = paths.get(name, paths["info"])
    cls_attr = f' class="{extra_class}"' if extra_class else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round"{cls_attr}>{body}</svg>'
    )
