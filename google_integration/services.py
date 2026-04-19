"""Google Sheets + Drive service layer.

Wraps the official Google API client with simple, intent-friendly methods so
views can stay thin. All methods accept a `GoogleAccount` and use cached
short-lived credentials (auto-refreshed in `oauth.credentials_for`).
"""
from __future__ import annotations

import math
from typing import Iterable

from googleapiclient.discovery import build

from .models import GoogleAccount
from .oauth import credentials_for

# When Google sends only themeColor (no rgbColor), approximate default sheet theme (0–1 RGB).
_THEME_RGB: dict[str, dict[str, float]] = {
    "TEXT1": {"red": 0.0, "green": 0.0, "blue": 0.0},
    "TEXT2": {"red": 0.4, "green": 0.4, "blue": 0.4},
    "BACKGROUND1": {"red": 1.0, "green": 1.0, "blue": 1.0},
    "BACKGROUND2": {"red": 0.89, "green": 0.94, "blue": 0.99},
    "ACCENT1": {"red": 66 / 255, "green": 133 / 255, "blue": 244 / 255},
    "ACCENT2": {"red": 234 / 255, "green": 67 / 255, "blue": 53 / 255},
    "ACCENT3": {"red": 251 / 255, "green": 188 / 255, "blue": 4 / 255},
    "ACCENT4": {"red": 52 / 255, "green": 168 / 255, "blue": 83 / 255},
    "ACCENT5": {"red": 1.0, "green": 109 / 255, "blue": 1 / 255},
    "ACCENT6": {"red": 70 / 255, "green": 189 / 255, "blue": 198 / 255},
    "HYPERLINK": {"red": 26 / 255, "green": 115 / 255, "blue": 232 / 255},
    "LINK": {"red": 26 / 255, "green": 115 / 255, "blue": 232 / 255},
    # Legacy single names sometimes seen in responses
    "TEXT": {"red": 0.0, "green": 0.0, "blue": 0.0},
    "BACKGROUND": {"red": 1.0, "green": 1.0, "blue": 1.0},
}


def _color_dict_from_rgb(color: dict | None) -> dict[str, float]:
    """Keep only numeric RGB(A) keys for JSON (Google uses 0–1 floats)."""
    if not color or not isinstance(color, dict):
        return {}
    out: dict[str, float] = {}
    for key in ("red", "green", "blue", "alpha"):
        v = color.get(key)
        if isinstance(v, float) and math.isnan(v):
            continue
        if isinstance(v, (int, float)):
            out[key] = float(v)
    return out


def _rgb_from_color_style(
    style: dict | None,
    palette: dict[str, dict[str, float]],
) -> dict[str, float]:
    if not style or not isinstance(style, dict):
        return {}
    rgb = style.get("rgbColor")
    if isinstance(rgb, dict) and any(k in rgb for k in ("red", "green", "blue")):
        return _color_dict_from_rgb(rgb)
    tc = style.get("themeColor")
    if isinstance(tc, str):
        resolved = palette.get(tc)
        if resolved:
            return dict(resolved)
    return {}


def _palette_from_response(resp: dict) -> dict[str, dict[str, float]]:
    """Merge defaults with this spreadsheet's spreadsheetTheme.themeColors."""
    palette: dict[str, dict[str, float]] = {k: dict(v) for k, v in _THEME_RGB.items()}
    st = (resp.get("properties") or {}).get("spreadsheetTheme") or {}
    for pair in st.get("themeColors") or []:
        if not isinstance(pair, dict):
            continue
        ct = pair.get("colorType")
        col = pair.get("color")
        if not isinstance(ct, str) or not isinstance(col, dict):
            continue
        rgb = col.get("rgbColor")
        if isinstance(rgb, dict) and any(k in rgb for k in ("red", "green", "blue")):
            parsed = _color_dict_from_rgb(rgb)
            if parsed:
                palette[ct] = parsed
    return palette


def _effective_background(
    eff: dict | None,
    palette: dict[str, dict[str, float]],
) -> dict[str, float]:
    if not eff or not isinstance(eff, dict):
        return {}
    from_style = _rgb_from_color_style(eff.get("backgroundColorStyle"), palette)
    if from_style:
        return from_style
    legacy = eff.get("backgroundColor")
    if isinstance(legacy, dict) and any(k in legacy for k in ("red", "green", "blue")):
        return _color_dict_from_rgb(legacy)
    return {}


def _effective_foreground(
    eff: dict | None,
    palette: dict[str, dict[str, float]],
) -> dict[str, float]:
    if not eff or not isinstance(eff, dict):
        return {}
    tf = eff.get("textFormat")
    if not isinstance(tf, dict):
        return {}
    from_style = _rgb_from_color_style(tf.get("foregroundColorStyle"), palette)
    if from_style:
        return from_style
    legacy = tf.get("foregroundColor")
    if isinstance(legacy, dict) and any(k in legacy for k in ("red", "green", "blue")):
        return _color_dict_from_rgb(legacy)
    return {}


def _sheets_service(account: GoogleAccount):
    creds = credentials_for(account)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _drive_service(account: GoogleAccount):
    creds = credentials_for(account)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Drive: spreadsheet listing
# ---------------------------------------------------------------------------

def list_spreadsheets(account: GoogleAccount, page_size: int = 50) -> list[dict]:
    """List spreadsheets the user can access via this app."""
    drive = _drive_service(account)
    resp = drive.files().list(
        q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
        pageSize=page_size,
        fields="files(id, name, modifiedTime, webViewLink)",
        orderBy="modifiedTime desc",
    ).execute()
    return resp.get("files", [])


# ---------------------------------------------------------------------------
# Sheets: CRUD for cells
# ---------------------------------------------------------------------------

def create_spreadsheet(account: GoogleAccount, title: str) -> dict:
    sheets = _sheets_service(account)
    body = {"properties": {"title": title}}
    resp = sheets.spreadsheets().create(
        body=body,
        fields="spreadsheetId,spreadsheetUrl,properties.title",
    ).execute()
    return resp


def get_spreadsheet_meta(account: GoogleAccount, spreadsheet_id: str) -> dict:
    sheets = _sheets_service(account)
    return sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="spreadsheetId,spreadsheetUrl,properties.title,sheets.properties",
    ).execute()


def get_values(
    account: GoogleAccount,
    spreadsheet_id: str,
    range_a1: str,
) -> list[list[str]]:
    sheets = _sheets_service(account)
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
    ).execute()
    return resp.get("values", [])


def get_grid_data(
    account: GoogleAccount,
    spreadsheet_id: str,
    range_a1: str,
) -> dict:
    """Return values + lightweight style metadata for a rendered sheet grid."""
    sheets = _sheets_service(account)
    resp = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        ranges=[range_a1],
        includeGridData=True,
        fields=(
            "properties(spreadsheetTheme(themeColors(colorType,color(rgbColor,themeColor)))),"
            "sheets(data(rowData(values("
            "formattedValue,effectiveValue,hyperlink,"
            "effectiveFormat("
            "backgroundColor,backgroundColorStyle(rgbColor,themeColor),"
            "horizontalAlignment,"
            "textFormat(bold,italic,foregroundColor,foregroundColorStyle(rgbColor,themeColor))"
            ")"
            "))))"
        ),
    ).execute()

    palette = _palette_from_response(resp)
    rows: list[list[str]] = []
    styles: list[list[dict]] = []

    for sheet in resp.get("sheets", []):
        for data_block in sheet.get("data", []):
            for row in data_block.get("rowData", []):
                row_values: list[str] = []
                row_styles: list[dict] = []
                for cell in row.get("values", []):
                    display_value = cell.get("formattedValue", "")
                    row_values.append(display_value)
                    eff = cell.get("effectiveFormat") or {}
                    tf = eff.get("textFormat") if isinstance(eff, dict) else None
                    tf = tf if isinstance(tf, dict) else {}
                    row_styles.append(
                        {
                            "bg": _effective_background(
                                eff if isinstance(eff, dict) else None, palette
                            ),
                            "text": _effective_foreground(
                                eff if isinstance(eff, dict) else None, palette
                            ),
                            "bold": bool(tf.get("bold")),
                            "italic": bool(tf.get("italic")),
                            "align": eff.get("horizontalAlignment", "") if isinstance(eff, dict) else "",
                            "hyperlink": cell.get("hyperlink", ""),
                        }
                    )
                rows.append(row_values)
                styles.append(row_styles)

    return {"values": rows, "styles": styles}


def update_values(
    account: GoogleAccount,
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[str]],
) -> dict:
    sheets = _sheets_service(account)
    body = {"values": values}
    return sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()


def append_rows(
    account: GoogleAccount,
    spreadsheet_id: str,
    range_a1: str,
    rows: Iterable[Iterable[str]],
) -> dict:
    sheets = _sheets_service(account)
    body = {"values": [list(r) for r in rows]}
    return sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


def clear_range(account: GoogleAccount, spreadsheet_id: str, range_a1: str) -> dict:
    sheets = _sheets_service(account)
    return sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        body={},
    ).execute()
