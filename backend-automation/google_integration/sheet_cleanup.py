"""Rebuild a single Google Sheet tab with verification-gated rows only.

Never touches other tabs. Used to strip inferred/historical noise from a CRM tab
(e.g. Sheet 2) while leaving team-owned tabs (e.g. Sheet1) unchanged.

Uses **one** Sheets API client per run so OAuth refreshes at most once (avoids
duplicate “401 → refresh” noise and redundant token round-trips).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import unquote

from googleapiclient.discovery import build

from google_integration.oauth import credentials_for
from google_integration.sheet_sync import SHEET_HEADER, build_sheet_row, resolve_google_sync_user
from google_integration.spreadsheet_id import normalize_spreadsheet_id

logger = logging.getLogger(__name__)

# Tabs we refuse to modify unless explicitly overridden (team / default sheets).
_FORBIDDEN_TAB_NORMALIZED = frozenset({"sheet1"})

# Read enough columns for sheets that put profile URLs outside A–G.
_READ_RANGE_COLUMNS = "A:Z"


def _is_instagram_or_legacy_profile_url(s: str) -> bool:
    """True for Instagram profile URLs; also accepts legacy LinkedIn /in|/pub cells."""
    u = (s or "").lower()
    if "instagram.com/" in u:
        # Exclude posts/reels/explore noise when scanning cells
        if any(x in u for x in ("/p/", "/reel/", "/reels/", "/explore/", "/stories/")):
            return False
        return True
    return "linkedin.com/in/" in u or "linkedin.com/pub/" in u


def _col_index_to_a1_letter(idx: int) -> str:
    """0 -> A, 3 -> D, 25 -> Z (cleanup reads A:Z only)."""
    if 0 <= idx < 26:
        return chr(ord("A") + idx)
    return f"Col{idx}"


def _pad_row(row: list[str], min_len: int) -> list[str]:
    r = list(row)
    while len(r) < min_len:
        r.append("")
    return r


def _cell_to_str(v) -> str:
    """Sheets API returns str, bool (checkboxes), int/float — normalize for parsing."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return str(v).strip()


def _normalize_sheet_rows(values: list[list]) -> list[list[str]]:
    return [[_cell_to_str(c) for c in row] for row in values]


def _url_from_sheets_cell(raw: str) -> str:
    """Turn a cell into a URL: plain https link, or first URL inside =HYPERLINK(...)."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("=") and "HYPERLINK" in s.upper():
        m = re.search(r'["\'](https?://[^"\']+)["\']', s, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"(https?://[^\s\"\'\)]+)", s)
        if m:
            return m.group(1).rstrip(",").strip()
    return s


def detect_instagram_url_column(header_row: list[str]) -> int:
    """Return 0-based column index for Instagram URL (defaults to 3 = column D)."""
    header_row = _pad_row(header_row, 26)
    for i, cell in enumerate(header_row):
        h = (cell or "").strip().lower()
        if "instagram" in h:
            return i
    for i, cell in enumerate(header_row):
        h = (cell or "").strip().lower()
        # Legacy sheets may still label the profile column with "linkedin".
        if "linkedin" in h:
            return i
    return 3


def infer_profile_column_from_data_rows(
    rows: list[list[str]],
    *,
    max_scan: int = 80,
) -> int | None:
    """When headers omit Instagram (or legacy LinkedIn), pick the column with the most profile URLs."""
    if len(rows) < 2:
        return None
    counts = [0] * 26
    end = min(len(rows), 1 + max_scan)
    for row in rows[1:end]:
        pad = _pad_row(row, 26)
        for j in range(26):
            t = _url_from_sheets_cell(_cell_to_str(pad[j]))
            if _is_instagram_or_legacy_profile_url(t):
                counts[j] += 1
    best = max(range(26), key=lambda i: counts[i])
    if counts[best] > 0:
        return best
    return None


def resolve_instagram_column_index(rows: list[list[str]]) -> tuple[int, str]:
    """Header-based detection, else vote from data rows."""
    header = rows[0] if rows else []
    col = detect_instagram_url_column(header)
    joined = " ".join(_cell_to_str(c) for c in header).lower()
    if "instagram" in joined or "linkedin" in joined:
        return col, "header"
    inferred = infer_profile_column_from_data_rows(rows)
    if inferred is not None:
        return inferred, "data_scan"
    return col, "default_d"


def extract_instagram_url_from_row(
    row: list[str],
    preferred_col: int,
) -> tuple[str, bool]:
    """Return (url_or_empty, used_fallback_scan).

    Prefer the detected column; if empty or non-profile text there, scan the row for
    ``instagram.com/<user>`` (or legacy LinkedIn /in|/pub).
    """
    row = _pad_row(row, max(preferred_col + 1, 26))

    raw_primary = row[preferred_col] if preferred_col < len(row) else ""
    primary = _url_from_sheets_cell(raw_primary)
    if primary and _is_instagram_or_legacy_profile_url(primary):
        return primary, False

    found = ""
    used_fallback = False
    for j, cell in enumerate(row):
        text = _url_from_sheets_cell((cell or "").strip())
        if not text:
            continue
        if _is_instagram_or_legacy_profile_url(text):
            found = text
            used_fallback = j != preferred_col or (not raw_primary.strip())
            break

    if found:
        return found, used_fallback

    if primary:
        return primary, False
    return "", False


def _sheets_v4_service(account):
    """Single Sheets v4 client — refresh access token at most once per process call."""
    creds = credentials_for(account)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _fetch_tab_pairs(sheets, spreadsheet_id: str) -> tuple[list[tuple[int, str]], list[str]]:
    """Return [(sheetId, title), ...] and title list from one metadata GET."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties(sheetId,title)",
    ).execute()
    pairs: list[tuple[int, str]] = []
    for s in meta.get("sheets", []):
        p = s.get("properties") or {}
        sid = p.get("sheetId")
        title = p.get("title")
        if sid is not None and isinstance(title, str) and title.strip():
            pairs.append((int(sid), title))
    titles = [t for _, t in pairs]
    return pairs, titles


def _get_values(sheets, spreadsheet_id: str, range_a1: str) -> list[list[str]]:
    """Load cell values with UNFORMATTED_VALUE so hyperlinked URLs are not blank.

    Default FORMATTED_VALUE often returns empty or link *labels* for Insert-link cells,
    which made column D look empty to our script even when the sheet shows URLs.
    """
    resp = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    raw = resp.get("values", [])
    return _normalize_sheet_rows(raw)


def _clear_range(sheets, spreadsheet_id: str, range_a1: str) -> dict:
    return (
        sheets.spreadsheets()
        .values()
        .clear(spreadsheetId=spreadsheet_id, range=range_a1, body={})
        .execute()
    )


def _update_values(sheets, spreadsheet_id: str, range_a1: str, values: list[list[str]]) -> dict:
    return (
        sheets.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        )
        .execute()
    )


def quote_tab_a1(tab: str, cell_range: str) -> str:
    """Build A1 notation for a tab name (handles spaces and quotes)."""
    t = (tab or "").strip()
    inner = t.replace("'", "''")
    return f"'{inner}'!{cell_range}"


def normalize_cleanup_tab_name(tab: str) -> str:
    return (tab or "").strip().lower().replace(" ", "")


def resolve_sheet_tab_title(
    sheets,
    spreadsheet_id: str,
    *,
    tab_hint: str | None,
    sheet_gid: int | None,
) -> str:
    """Return the exact tab title as stored in Google (fixes 'Unable to parse range' mismatches)."""
    pairs, titles = _fetch_tab_pairs(sheets, spreadsheet_id)
    if not titles:
        raise ValueError("Spreadsheet has no sheets or metadata could not be read.")

    if sheet_gid is not None:
        for sid, title in pairs:
            if sid == sheet_gid:
                return title
        raise ValueError(
            f"No tab with sheetId={sheet_gid}. Available (gid → title): "
            f"{[(s, t) for s, t in pairs]}",
        )

    hint = (tab_hint or "").strip()
    if not hint:
        raise ValueError('Provide --tab "Exact Name" or --sheet-gid from the spreadsheet URL.')

    if hint in titles:
        return hint

    hl = hint.lower()
    for title in titles:
        if title.lower() == hl:
            return title

    hn = hl.replace(" ", "")
    for title in titles:
        if title.lower().replace(" ", "") == hn:
            return title

    raise ValueError(
        f"No tab matching {hint!r}. Available tab titles: {titles}. "
        "Tip: open the spreadsheet URL with #gid=SHEET_ID — run with --sheet-gid SHEET_ID "
        "to target the correct tab.",
    )


def assert_safe_target_tab(tab: str, *, force_unsafe_tab: bool = False) -> None:
    """Raise ValueError if tab looks like the protected default Sheet1."""
    if force_unsafe_tab:
        return
    n = normalize_cleanup_tab_name(tab)
    if n in _FORBIDDEN_TAB_NORMALIZED:
        raise ValueError(
            "Refusing to modify this tab name (matches Sheet1). "
            'Pass --force-unsafe-tab only if you accept rewriting Sheet1.',
        )


def extract_public_id_from_instagram_url(url: str) -> str | None:
    """Extract Instagram username (or legacy LinkedIn /in|/pub id) from a sheet cell URL."""
    raw = (url or "").strip()
    if not raw:
        return None

    low = raw.lower()

    # Instagram profile URLs / bare @handles — do not run LinkedIn paths through IG parser.
    if "instagram.com/" in low or ("://" not in raw and "/" not in raw):
        try:
            from linkedin.url_utils import url_to_public_id

            pid = url_to_public_id(raw)
            if pid:
                return pid
        except Exception:
            pass
        ig = re.search(r"instagram\.com/([^/?#\"')\s]+)", raw, re.IGNORECASE)
        if ig:
            handle = unquote(ig.group(1)).strip().lstrip("@")
            reserved = {
                "p", "reel", "reels", "stories", "explore", "accounts",
                "direct", "about", "legal", "tags", "tv",
            }
            if handle and handle.lower() not in reserved:
                return handle
        if "://" not in raw and "/" not in raw:
            handle = raw.lstrip("@").strip()
            return handle or None
        return None

    # Legacy LinkedIn cells still present on some sheets.
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?#\"')\s]+)", raw, re.IGNORECASE)
    if not m:
        return None
    return unquote(m.group(1)).strip() or None


def _pick_primary_pipeline_deal(lead):
    """Best-effort display deal: Connected > Pending > Qualified."""
    from linkedin.enums import ProfileState

    order = (ProfileState.CONNECTED.value, ProfileState.PENDING.value, ProfileState.QUALIFIED.value)
    for st in order:
        d = lead.deal_set.filter(state=st).first()
        if d:
            return d
    return None


def lead_for_sheet_row(url_cell: str):
    """Resolve a CRM Lead from a Instagram URL cell (flexible matching)."""
    from django.db.models.functions import Lower

    from crm.models import Lead

    url = (url_cell or "").strip()
    if not url:
        return None

    lead = Lead.objects.filter(instagram_url=url).first()
    if lead:
        return lead

    pid = extract_public_id_from_instagram_url(url)
    if pid:
        lead = Lead.objects.filter(public_identifier__iexact=pid).first()
        if lead:
            return lead

    base = url.rstrip("/").lower()
    return Lead.objects.annotate(_lu=Lower("instagram_url")).filter(_lu=base).first()


def rebuild_verified_tab_only(
    *,
    spreadsheet_id: str,
    tab: str | None,
    sheet_gid: int | None,
    dry_run: bool,
    force_unsafe_tab: bool,
    connected_only: bool = False,
    pipeline_only: bool = False,
) -> dict:
    """Read tab A:Z, drop rows without CRM lead / gate, dedupe by lead, rewrite tab.

    With ``connected_only=True``, keep leads that have any Deal in ``CONNECTED`` state
    (no OutreachEvent / confidence gate).

    With ``pipeline_only=True``, keep leads that have any Deal in Qualified, Pending,
    or Connected (drops CRM leads that only have Failed/Completed deals or no deals).

    Default uses ``lead_sheet_export_verification``.

    Returns stats dict. Does not read or write any other sheet tab.
    """
    from google_integration.models import GoogleAccount
    from linkedin.enums import ProfileState
    from linkedin.models import SiteConfig
    from linkedin.outreach_tracking import lead_sheet_export_verification

    sid = normalize_spreadsheet_id(spreadsheet_id.strip())
    if not sid:
        raise ValueError("spreadsheet_id is empty")

    cfg = SiteConfig.load()
    user = resolve_google_sync_user(cfg)
    if not user:
        raise RuntimeError("No Google sync user — connect Google OAuth (SiteConfig or superuser).")

    account = GoogleAccount.objects.filter(user=user).first()
    if not account or not account.is_connected:
        raise RuntimeError(f"User {user} has no connected GoogleAccount")

    logger.info("Opening Google Sheets API (single client — one OAuth refresh max)")
    sheets = _sheets_v4_service(account)

    resolved_tab = resolve_sheet_tab_title(
        sheets,
        sid,
        tab_hint=tab,
        sheet_gid=sheet_gid,
    )
    assert_safe_target_tab(resolved_tab, force_unsafe_tab=force_unsafe_tab)

    rng = quote_tab_a1(resolved_tab, _READ_RANGE_COLUMNS)
    logger.info("Reading range %s (wide range for legacy column layouts)", rng)
    rows = _get_values(sheets, sid, rng)

    header = rows[0] if rows else []
    ig_col, ig_src = resolve_instagram_column_index(rows)
    logger.info(
        "Instagram URL column: %s (%s) [%s]",
        _col_index_to_a1_letter(ig_col),
        (header[ig_col] if ig_col < len(header) else "") or "(inferred)",
        ig_src,
    )

    verification_reject_counts: Counter[str] = Counter()

    if pipeline_only and connected_only:
        raise ValueError("Use only one of pipeline_only or connected_only.")

    mode = "export_verified"
    if connected_only:
        mode = "connected_only"
    elif pipeline_only:
        mode = "pipeline_only"

    stats = {
        "tab": resolved_tab,
        "tab_requested": (tab or "").strip(),
        "sheet_gid_requested": sheet_gid,
        "spreadsheet_id": sid,
        "instagram_column_index": ig_col,
        "instagram_column_letter": _col_index_to_a1_letter(ig_col),
        "instagram_detection": ig_src,
        "rows_read": max(0, len(rows) - 1),
        "mode": mode,
        "dropped_no_url": 0,
        "dropped_no_lead": 0,
        "dropped_no_deals": 0,
        "dropped_not_in_pipeline": 0,
        "dropped_not_connected": 0,
        "dropped_not_verified": 0,
        "verification_reject_counts": {},
        "duplicate_urls_collapsed": 0,
        "urls_from_row_scan_fallback": 0,
        "kept": 0,
        "dry_run": dry_run,
        "connected_only": connected_only,
        "pipeline_only": pipeline_only,
    }

    seen_lead_ids: set[int] = set()
    verified_leads: list = []

    for i, row in enumerate(rows):
        if i == 0:
            continue  # header
        url_cell, used_fallback = extract_instagram_url_from_row(row, ig_col)
        if used_fallback:
            stats["urls_from_row_scan_fallback"] += 1

        if not (url_cell or "").strip():
            stats["dropped_no_url"] += 1
            continue

        lead = lead_for_sheet_row(url_cell)
        if not lead:
            stats["dropped_no_lead"] += 1
            continue

        if lead.pk in seen_lead_ids:
            stats["duplicate_urls_collapsed"] += 1
            continue

        if not lead.deal_set.exists():
            stats["dropped_no_deals"] += 1
            continue

        if connected_only:
            if not lead.deal_set.filter(state=ProfileState.CONNECTED.value).exists():
                stats["dropped_not_connected"] += 1
                continue
            seen_lead_ids.add(lead.pk)
            verified_leads.append((lead, "connected_deal", "Connected"))
            continue

        if pipeline_only:
            deal = _pick_primary_pipeline_deal(lead)
            if deal is None:
                stats["dropped_not_in_pipeline"] += 1
                continue
            seen_lead_ids.add(lead.pk)
            verified_leads.append((lead, "pipeline_active", deal.state))
            continue

        ok, reason, status_label = lead_sheet_export_verification(lead)
        if not ok:
            stats["dropped_not_verified"] += 1
            verification_reject_counts[(reason or "unknown")] += 1
            continue

        seen_lead_ids.add(lead.pk)
        verified_leads.append((lead, reason, status_label))

    verified_leads.sort(key=lambda x: x[0].pk)

    stats["kept"] = len(verified_leads)
    stats["verification_reject_counts"] = dict(
        sorted(verification_reject_counts.items(), key=lambda x: (-x[1], x[0]))
    )

    if dry_run:
        logger.info(
            "Dry-run: would write %s rows to tab %r (%s)",
            stats["kept"],
            resolved_tab,
            stats["mode"],
        )
        return stats

    body: list[list[str]] = [SHEET_HEADER]
    for lead, reason, status_label in verified_leads:
        body.append(build_sheet_row(lead, status_label=status_label, verification_reason=reason))

    logger.info("Clearing and rewriting tab %r (%s rows)", resolved_tab, len(body))
    _clear_range(sheets, sid, quote_tab_a1(resolved_tab, "A2:Z100000"))
    _update_values(sheets, sid, quote_tab_a1(resolved_tab, "A1"), body)

    logger.info(
        "Rebuilt tab %r: %s rows (%s) — dropped: no_url=%s no_lead=%s no_deals=%s "
        "not_pipeline=%s not_connected=%s not_verified=%s dup=%s",
        resolved_tab,
        stats["kept"],
        stats["mode"],
        stats["dropped_no_url"],
        stats["dropped_no_lead"],
        stats["dropped_no_deals"],
        stats["dropped_not_in_pipeline"],
        stats["dropped_not_connected"],
        stats["dropped_not_verified"],
        stats["duplicate_urls_collapsed"],
    )
    return stats
