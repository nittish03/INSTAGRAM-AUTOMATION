"""Google Sheets + Drive service layer.

Wraps the official Google API client with simple, intent-friendly methods so
views can stay thin. All methods accept a `GoogleAccount` and use cached
short-lived credentials (auto-refreshed in `oauth.credentials_for`).
"""
from __future__ import annotations

from typing import Iterable

from googleapiclient.discovery import build

from .models import GoogleAccount
from .oauth import credentials_for


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
            "sheets(data(rowData(values("
            "formattedValue,effectiveValue,hyperlink,"
            "effectiveFormat(backgroundColor,textFormat,horizontalAlignment)"
            "))))"
        ),
    ).execute()

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
                    row_styles.append(
                        {
                            "bg": (cell.get("effectiveFormat", {}) or {}).get("backgroundColor", {}),
                            "text": ((cell.get("effectiveFormat", {}) or {}).get("textFormat", {}) or {}).get(
                                "foregroundColor", {}
                            ),
                            "bold": bool(((cell.get("effectiveFormat", {}) or {}).get("textFormat", {}) or {}).get("bold")),
                            "italic": bool(((cell.get("effectiveFormat", {}) or {}).get("textFormat", {}) or {}).get("italic")),
                            "align": (cell.get("effectiveFormat", {}) or {}).get("horizontalAlignment", ""),
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
