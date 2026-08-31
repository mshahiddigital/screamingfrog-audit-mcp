"""Brand tokens and the credit block carried by every generated report.

One place, so the workbook, the HTML and the markdown can never drift into
three slightly different looks.

Colours are hex WITHOUT the leading '#', because openpyxl wants them that way;
`css()` adds it back for the HTML report.
"""

from __future__ import annotations

# ── Identity ─────────────────────────────────────────────────────────────────
# Every report this tool generates carries the credit line below. Override the
# audited-business name per report; the credit itself is part of the tool.
AUTHOR = "Muhammad Shahid"
AUTHOR_SITE = "https://mshahid.com"
AUTHOR_SITE_SHORT = "mshahid.com"
STUDIO = "M Shahid Digital"
TOOL = "screamingfrog-audit-mcp"

CREDIT_LINE = f"Generated with {TOOL} by {AUTHOR} — {AUTHOR_SITE_SHORT}"
CREDIT_LONG = (
    f"This audit was produced with {TOOL}, an open-source Screaming Frog "
    f"automation built by {AUTHOR} at {STUDIO}. {AUTHOR_SITE}"
)

# ── Palette ──────────────────────────────────────────────────────────────────
PURPLE = "9D0BC4"        # primary
VIOLET = "B80CF2"        # accent
CREAM = "F5F0E8"         # page ground
CARD_SAND = "EFE7D6"     # raised surface
LIGHT_CREAM = "FBF6EC"   # row banding
TEXT = "111827"
TEXT_2 = "374151"
MUTED = "6B7280"
BORDER = "E6DED1"
WHITE = "FFFFFF"

GREEN = "16A34A"
AMBER = "D97706"
RED = "DC2626"

# State, never identity.
PRIORITY_FILL = {"High": RED, "Medium": AMBER, "Low": MUTED}
PRIORITY_TINT = {"High": "FDE8E8", "Medium": "FEF3E2", "Low": "F1F1F3"}

# Status-code banding for the crawl sheets.
STATUS_TINT = {"2": "E9F7EF", "3": "FEF3E2", "4": "FDE8E8", "5": "FBD5D5", "0": "F1F1F3"}


def band(score: int) -> tuple[str, str]:
    """Health score to (label, hex colour)."""
    if score >= 90:
        return "Excellent", GREEN
    if score >= 75:
        return "Good", GREEN
    if score >= 50:
        return "Needs work", AMBER
    return "Poor", RED


def css(name: str) -> str:
    return "#" + name


def report_title(site: str) -> str:
    return f"Technical SEO Audit — {site}"
