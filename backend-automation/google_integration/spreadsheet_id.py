"""Parse Google Sheets spreadsheet IDs from URLs or plain strings."""
from __future__ import annotations

import re

# docs.google.com/spreadsheets/d/<id>/...
_SPREADSHEET_IN_PATH = re.compile(
    r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)
_ID_TOKEN = re.compile(r"^[a-zA-Z0-9_-]+$")


def normalize_spreadsheet_id(raw: str | None) -> str:
    """Return the API spreadsheet id only.

    Accepts:
    - Full URL: ``https://docs.google.com/spreadsheets/d/<id>/edit?gid=0#gid=0``
    - Bare id: ``<id>``
    """
    if not raw:
        return ""
    s = raw.strip()
    if not s:
        return ""

    normalized = s.replace("\\", "/")
    m = _SPREADSHEET_IN_PATH.search(normalized)
    if m:
        return m.group(1)

    # Bare id or leading id before /edit, ?query, #fragment
    head = normalized.split("/")[0].split("?")[0].split("#")[0].strip()
    if _ID_TOKEN.match(head):
        return head

    # Rare: pasted string starts with path fragment only
    for part in re.split(r"[/\s?#&]+", normalized):
        part = part.strip()
        if part and _ID_TOKEN.match(part) and len(part) >= 10:
            return part

    return head
