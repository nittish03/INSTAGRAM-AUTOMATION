"""Explicit outreach events, raw diagnostic logs, and sheet export eligibility.

Principle: separate inference (Deal state + heuristics), explicit events (what we did / saw),
and export-grade verification (high-confidence outcomes only).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def raw_log(
    level: str,
    category: str,
    message: str,
    *,
    payload: dict[str, Any] | None = None,
    lead_id: int | None = None,
    campaign_id: int | None = None,
    task_id: int | None = None,
) -> None:
    from linkedin.models import SystemRawLog

    try:
        SystemRawLog.objects.create(
            level=level,
            category=category,
            message=(message or "")[:8000],
            payload=payload or {},
            lead_id=lead_id,
            campaign_id=campaign_id,
            task_id=task_id,
        )
    except Exception:
        logger.debug("raw_log persist failed", exc_info=True)


def emit_outreach_event(
    event_type: str,
    *,
    lead=None,
    deal=None,
    campaign=None,
    public_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    from linkedin.models import OutreachEvent

    lead_obj = lead
    deal_obj = deal
    camp = campaign
    if deal_obj and lead_obj is None:
        lead_obj = deal_obj.lead
    if deal_obj and camp is None:
        camp = deal_obj.campaign

    pid = public_id or (getattr(lead_obj, "public_identifier", "") or "")
    OutreachEvent.objects.create(
        event_type=event_type,
        lead_id=lead_obj.pk if lead_obj else None,
        deal_id=deal_obj.pk if deal_obj else None,
        campaign_id=camp.pk if camp else None,
        public_identifier=(pid or "")[:200],
        metadata=metadata or {},
    )


def update_deal_inference(deal, source: str, confidence: float) -> None:
    from django.utils import timezone

    deal.follow_assessment_source = (source or "")[:64]
    deal.follow_assessment_confidence = float(confidence)
    deal.follow_assessed_at = timezone.now()
    deal.save(
        update_fields=[
            "follow_assessment_source",
            "follow_assessment_confidence",
            "follow_assessed_at",
        ]
    )


def lead_sheet_export_verification(lead, *, config_user=None) -> tuple[bool, str, str]:
    """Whether this lead may be written to the business Google Sheet.

    Eligible when either:
    - a successful ``message_sent`` outreach event exists (DM-first path), or
    - a CONNECTED deal **and** an explicit ``follow_back_detected`` event
      (legacy follow path) whose metadata satisfies confidence rules.

    Returns (eligible, reason_code, status_label_for_sheet_column).
    """
    from linkedin.enums import ProfileState
    from linkedin.models import OutreachEvent, SiteConfig

    message_sent = (
        OutreachEvent.objects.filter(
            lead=lead,
            event_type=OutreachEvent.EventType.MESSAGE_SENT,
        )
        .order_by("-created_at")
        .first()
    )
    if message_sent is not None:
        return True, "message_sent", "Messaged"

    if not lead.deal_set.filter(state=ProfileState.CONNECTED).exists():
        return False, "not_connected", ""

    cfg = SiteConfig.load(config_user)
    min_api = float(cfg.sheet_export_min_confidence_api)
    min_after = float(cfg.sheet_export_min_confidence_after_follow)

    detects = list(
        OutreachEvent.objects.filter(
            lead=lead,
            event_type=OutreachEvent.EventType.FOLLOW_BACK_DETECTED,
        ).order_by("created_at")
    )
    if not detects:
        return False, "no_connection_detected_event", ""

    latest = detects[-1]
    meta = latest.metadata or {}
    src = (meta.get("source") or "").strip()
    conf = float(meta.get("confidence") or 0.0)

    # api_degree_1 kept for backward compat with old OutreachEvent rows
    high_conf_sources = {"api_follows_viewer", "api_degree_1", "ui_message_button"}
    if src in high_conf_sources and conf >= min_api:
        return True, "verified_api_first_degree", "Verified (follow-back)"

    invites = list(
        OutreachEvent.objects.filter(
            lead=lead,
            event_type=OutreachEvent.EventType.FOLLOW_SENT,
        ).order_by("created_at")
    )
    if not invites:
        return False, "no_invite_for_non_api_path", ""

    last_invite_at = invites[-1].created_at
    if latest.created_at < last_invite_at:
        return False, "detection_before_last_invite", ""

    if conf >= min_after and src in high_conf_sources:
        return True, "verified_after_invite", "Accepted (post-follow)"

    return False, "insufficient_confidence_or_source", ""
