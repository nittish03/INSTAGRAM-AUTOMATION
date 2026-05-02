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

# A–J: column H Review = human; I = export date; J = last follow-up (from ActionLog) when known.
SHEET_HEADER = [
    "Name",
    "Company Name",
    "Position",
    "LinkedIn Profile",
    "Connected",
    "Status",
    "Action",
    "Review",
    "Date",
    "Last Follow up Date",
]

# After normalize_sheet_status(), only these appear in column F (dropdown-safe).
SHEET_NORMALIZED_STATUSES = frozenset({"Qualified", "Pending", "Connected"})

# Bot-written Action column labels — tiered follow-up (data validation must match exactly).
SHEET_ACTIVE_FOLLOW_UP = "Follow up"
SHEET_ACTIVE_FOLLOW_UP_1 = "Follow up-1"
SHEET_ACTIVE_FOLLOW_UP_2 = "Follow up-2"
SHEET_ACTIVE_FOLLOW_UP_3 = "Follow up-3"


def normalize_sheet_status(raw: str) -> str:
    """Map internal/export labels to CRM dropdown values (Qualified / Pending / Connected).

    **Deterministic:** every ``status_label`` produced by the app is either already one of
    those three or is mapped from the fixed set below — suitable for a strict Status dropdown.

    Maps export-verification labels onto ``Connected`` so they match a simple 3-option sheet.
    """
    from linkedin.enums import ProfileState

    s = (raw or "").strip()
    mapped_to_connected = frozenset(
        {
            "Verified (API)",
            "Accepted (post-invite)",
            "Unverified (manual bypass)",
        }
    )
    if s in mapped_to_connected:
        return ProfileState.CONNECTED.value
    if s in (
        ProfileState.QUALIFIED.value,
        ProfileState.PENDING.value,
        ProfileState.CONNECTED.value,
    ):
        return s
    logger.warning("Unknown sheet status label %r — using Pending for dropdown safety", raw)
    return ProfileState.PENDING.value


def derive_active_label(normalized_status: str) -> str:
    """Pick Action-column dropdown value from normalized CRM status (tiered follow-up)."""
    from linkedin.enums import ProfileState

    return {
        ProfileState.QUALIFIED.value: SHEET_ACTIVE_FOLLOW_UP,
        ProfileState.PENDING.value: SHEET_ACTIVE_FOLLOW_UP_1,
        ProfileState.CONNECTED.value: SHEET_ACTIVE_FOLLOW_UP_2,
    }.get(normalized_status, SHEET_ACTIVE_FOLLOW_UP)


def sheet_status_keywords_reference() -> dict[str, list[str]]:
    """Documentation helper: internal labels vs normalized Status (for operators)."""
    from linkedin.enums import ProfileState

    return {
        "normalized_status_dropdown_values": sorted(SHEET_NORMALIZED_STATUSES),
        "maps_to_connected": ["Verified (API)", "Accepted (post-invite)", "Unverified (manual bypass)"],
        "passthrough_unchanged": [
            ProfileState.QUALIFIED.value,
            ProfileState.PENDING.value,
            ProfileState.CONNECTED.value,
        ],
        "action_labels_emitted": [
            SHEET_ACTIVE_FOLLOW_UP,
            SHEET_ACTIVE_FOLLOW_UP_1,
            SHEET_ACTIVE_FOLLOW_UP_2,
        ],
    }


def _ensure_header_row(account, sid: str, tab: str) -> None:
    """Idempotently write A1:J1 if the header row is missing/empty."""
    existing = get_values(account, sid, f"{tab}!A1:J1")
    row = existing[0] if existing else []
    if not row or all(not (c or "").strip() for c in row):
        update_values(account, sid, f"{tab}!A1:J1", [SHEET_HEADER])


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


def _sheet_entry_date_cell() -> str:
    """Column **Date**: local date when this row is written (export / rebuild)."""
    return timezone.localtime(timezone.now()).strftime("%m/%d/%Y")


def _sheet_last_follow_up_date_cell(lead: "Lead") -> str:
    """Column **Last Follow up Date**: latest successful follow-up action for this lead, if any."""
    from linkedin.models import ActionLog

    pid = (lead.public_identifier or "").strip()
    if not pid:
        return ""
    log = (
        ActionLog.objects.filter(
            target_public_id=pid,
            action_type=ActionLog.ActionType.FOLLOW_UP,
            status=ActionLog.Status.SUCCESS,
        )
        .order_by("-created_at")
        .only("created_at")
        .first()
    )
    if not log:
        return ""
    return timezone.localtime(log.created_at).strftime("%m/%d/%Y")


def build_sheet_row(
    lead: "Lead",
    *,
    status_label: str,
    verification_reason: str = "",
) -> list[str]:
    """One row aligned to A–J.

    Column **Status** is normalized for dropdown validation. Column **Action** holds the
    tiered follow-up label derived from that status. **Review** stays blank for humans.
    **Date** is today's date (local tz) when the row is produced. **Last Follow up Date**
    is filled when we have a successful ``ActionLog`` FOLLOW_UP for this lead's public id.
    ``verification_reason`` is not written to the sheet (log-only).
    """
    name = f"{lead.first_name} {lead.last_name}".strip()
    if not name:
        name = lead.public_identifier or ""
    norm = normalize_sheet_status(status_label)
    active = derive_active_label(norm)
    return [
        name,
        lead.company_name or "",
        _lead_position(lead),
        lead.linkedin_url or "",
        "TRUE",
        norm,
        active,
        "",
        _sheet_entry_date_cell(),
        _sheet_last_follow_up_date_cell(lead),
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
            f"{tab}!A{row_idx}:J{row_idx}",
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
