"""Push CRM leads to a configured Google Sheet (append rows).

Exports are **verification-gated**: rows represent decision-grade outcomes only,
not inferred Deal states. Eligibility is driven by explicit ``OutreachEvent``
records (connection_detected, invite_sent) and confidence thresholds in SiteConfig.

Raw diagnostic data lives in ``SystemRawLog``; never mix it with sheet rows.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.utils import timezone

from google_integration.models import GoogleAccount
from google_integration.services import get_values, update_values
from google_integration.spreadsheet_id import normalize_spreadsheet_id

if TYPE_CHECKING:
    from crm.models.lead import Lead

logger = logging.getLogger(__name__)

SHEET_HEADER = [
    "Name",
    "Company Name",
    "Position",
    "LinkedIn Profile",
    "Connected",
    "Status",
    "Action",
]


def _ensure_header_row(account, sid: str, tab: str) -> None:
    """Idempotently write A1:G1 if the header row is missing/empty."""
    existing = get_values(account, sid, f"{tab}!A1:G1")
    row = existing[0] if existing else []
    if not row or all(not (c or "").strip() for c in row):
        update_values(account, sid, f"{tab}!A1:G1", [SHEET_HEADER])


def _next_row_index(account, sid: str, tab: str) -> int:
    """Lowest 1-based row index with no data in column A (minimum 2 to skip header)."""
    col_a = get_values(account, sid, f"{tab}!A:A")
    return max(len(col_a) + 1, 2)


def resolve_google_sync_user(config) -> User | None:
    """User whose OAuth tokens are used for Sheets (explicit sync user or first connected superuser)."""
    u = getattr(config, "google_sheet_sync_user", None)
    if u is not None:
        return u
    for user in User.objects.filter(is_superuser=True).select_related("google_account"):
        ga = getattr(user, "google_account", None)
        if ga and ga.is_connected:
            return user
    return None


def _lead_position(lead: "Lead") -> str:
    pd = lead.profile_data if isinstance(lead.profile_data, dict) else None
    if not pd:
        return ""
    headline = (pd.get("headline") or "").strip()
    if headline:
        return headline
    positions = pd.get("positions") or []
    if positions and isinstance(positions[0], dict):
        return (positions[0].get("title") or "").strip()
    return ""


def build_sheet_row(
    lead: "Lead",
    *,
    status_label: str,
    verification_reason: str,
) -> list[str]:
    """One row aligned to A–G. ``verification_reason`` is an internal audit code (export path)."""
    name = f"{lead.first_name} {lead.last_name}".strip()
    if not name:
        name = lead.public_identifier or ""
    return [
        name,
        lead.company_name or "",
        _lead_position(lead),
        lead.linkedin_url or "",
        "TRUE",
        status_label,
        verification_reason,
    ]


def sync_lead_to_google_sheet(
    lead: "Lead",
    *,
    bypass_verification: bool = False,
) -> bool:
    """Append one lead row to the configured sheet. Returns True if a row was written.

    Requires a CONNECTED deal plus export verification (see ``lead_sheet_export_verification``),
    unless ``bypass_verification`` is True (superuser-only emergency — still requires CONNECTED deal).
    """
    from linkedin.enums import ProfileState
    from linkedin.models import SiteConfig
    from linkedin.outreach_tracking import lead_sheet_export_verification

    cfg = SiteConfig.load()
    if not cfg.google_sheet_sync_enabled:
        return False
    sid = normalize_spreadsheet_id(cfg.google_sheet_id or "")
    if not sid:
        logger.debug("google_sheet_sync enabled but google_sheet_id empty — skip")
        return False
    if lead.sheet_exported_at is not None:
        return False

    if not lead.linkedin_url:
        return False
    if lead.profile_data is None:
        return False

    has_connected_deal = lead.deal_set.filter(state=ProfileState.CONNECTED).exists()
    if not has_connected_deal:
        return False

    ok_verify, reason_code, status_label = lead_sheet_export_verification(lead)
    if not bypass_verification:
        if not ok_verify:
            logger.info("Google Sheet sync skipped lead pk=%s (%s)", lead.pk, reason_code)
            return False
    else:
        if ok_verify:
            reason_code = f"bypass_prefix:{reason_code}"
        else:
            status_label = "Unverified (manual bypass)"
            reason_code = "bypass_verification"

    user = resolve_google_sync_user(cfg)
    if not user:
        logger.warning("Google Sheet sync: no user — set SiteConfig.google_sheet_sync_user or connect Google as a superuser")
        return False

    account = GoogleAccount.objects.filter(user=user).first()
    if not account or not account.is_connected:
        logger.warning("Google Sheet sync: user %s has no connected GoogleAccount", user)
        return False

    tab = (cfg.google_sheet_tab or "Sheet1").strip() or "Sheet1"

    try:
        _ensure_header_row(account, sid, tab)
        row_idx = _next_row_index(account, sid, tab)
        update_values(
            account,
            sid,
            f"{tab}!A{row_idx}:G{row_idx}",
            [build_sheet_row(lead, status_label=status_label, verification_reason=reason_code)],
        )
    except Exception:
        logger.exception("Google Sheet sync failed for lead pk=%s", lead.pk)
        return False

    LeadModel = lead.__class__
    LeadModel.objects.filter(pk=lead.pk, sheet_exported_at__isnull=True).update(
        sheet_exported_at=timezone.now()
    )
    logger.info("Google Sheet sync: appended lead pk=%s (%s) [%s]", lead.pk, lead.public_identifier, reason_code)
    return True
