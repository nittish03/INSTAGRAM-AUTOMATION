# linkedin/tasks/check_pending.py
"""Check pending task — checks one PENDING profile, self-reschedules with backoff."""
from __future__ import annotations

import logging

from termcolor import colored

from django.db import transaction

from linkedin.conf import bot_time_limits_enabled
from linkedin.db.deals import deal_to_profile_dict, set_profile_state
from linkedin.enums import ProfileState
from linkedin.exceptions import SkipProfile

logger = logging.getLogger(__name__)


def handle_check_pending(task, session, qualifiers):
    from crm.models import Deal
    from linkedin.actions.status import get_connection_assessment
    from linkedin.models import OutreachEvent
    from linkedin.outreach_tracking import emit_outreach_event, update_deal_inference
    from linkedin.tasks.connect import enqueue_check_pending, enqueue_follow_up

    payload = task.payload
    public_id = payload.get("public_id")
    if not public_id:
        logger.error("check_pending: missing public_id in task %s", task.pk)
        return

    campaign_id = payload["campaign_id"]
    backoff_hours = payload.get("backoff_hours", 24)
    owner_id = getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(owner_id, int):
        owner_id = None
    linkedin_profile_id = getattr(getattr(session, "linkedin_profile", None), "pk", None)
    if not isinstance(linkedin_profile_id, int):
        linkedin_profile_id = None

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 check_pending", "magenta", attrs=["bold"]), public_id,
    )

    deal = Deal.objects.filter(
        lead__public_identifier=public_id, 
        campaign=session.campaign
    ).select_related("lead").first()

    if deal is None:
        raise RuntimeError(f"check_pending: no Deal found for {public_id}")

    profile_dict = deal_to_profile_dict(deal)
    profile = profile_dict.get("profile") or profile_dict
    
    # Age limit: auto-fail if PENDING for > 30 days
    from datetime import timedelta
    from django.utils import timezone
    if bot_time_limits_enabled() and deal.creation_date < timezone.now() - timedelta(days=30):
        logger.info("[%s] Deal for %s expired (> 30 days PENDING) — marking FAILED", session.campaign, public_id)
        set_profile_state(session, public_id, ProfileState.FAILED.value, reason="Expired: PENDING for > 30 days")
        return

    try:
        assessment = get_connection_assessment(session, profile)
    except SkipProfile as e:
        logger.warning(
            "Could not verify pending status for %s (%s) — keeping Pending and rescheduling",
            public_id,
            e,
        )
        new_backoff = min(backoff_hours * 2, 6)
        with transaction.atomic():
            deal.backoff_hours = new_backoff
            deal.save(update_fields=["backoff_hours"])
        enqueue_check_pending(
            campaign_id,
            public_id,
            backoff_hours=new_backoff,
            deal=deal,
            owner_id=owner_id,
            linkedin_profile_id=linkedin_profile_id,
        )
        return

    verified_connected = (
        assessment.state == ProfileState.CONNECTED
        and assessment.source == "api_degree_1"
    )
    if assessment.state == ProfileState.CONNECTED and not verified_connected:
        logger.info(
            "%s looked connected via %s but is not API degree-1 yet — keeping Pending",
            public_id,
            assessment.source,
        )

    if verified_connected and deal:
        update_deal_inference(deal, assessment.source, assessment.confidence)
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            deal=deal,
            lead=deal.lead,
            campaign=session.campaign,
            public_id=public_id,
            metadata={
                "source": assessment.source,
                "confidence": assessment.confidence,
                "via": "check_pending",
            },
        )

    state_to_store = ProfileState.CONNECTED if verified_connected else assessment.state
    if assessment.state == ProfileState.CONNECTED and not verified_connected:
        state_to_store = ProfileState.PENDING

    set_profile_state(session, public_id, state_to_store.value)

    if verified_connected:
        if deal and deal.lead_id:
            from google_integration.sheet_sync import sync_lead_to_google_sheet

            sync_lead_to_google_sheet(deal.lead, config_user=owner_id)
        enqueue_follow_up(
            campaign_id,
            public_id,
            deal=deal,
            owner_id=owner_id,
            linkedin_profile_id=linkedin_profile_id,
        )
    elif state_to_store == ProfileState.PENDING:
        if deal and deal.lead_id:
            from google_integration.sheet_sync import sync_pending_lead_to_google_sheet

            sync_pending_lead_to_google_sheet(
                deal.lead,
                reason_code="check_pending_ui_pending",
                config_user=owner_id,
            )
        new_backoff = min(backoff_hours * 2, 6)
        with transaction.atomic():
            if deal:
                deal.backoff_hours = new_backoff
                deal.save(update_fields=["backoff_hours"])
        delay_hours = enqueue_check_pending(
            campaign_id,
            public_id,
            backoff_hours=new_backoff,
            deal=deal,
            owner_id=owner_id,
            linkedin_profile_id=linkedin_profile_id,
        )
        logger.info(
            "%s still pending — scheduled in %.1fh (backoff %.1fh → %.1fh)",
            public_id, delay_hours, backoff_hours, new_backoff,
        )
    elif state_to_store == ProfileState.QUALIFIED and deal and deal.lead_id:
        from google_integration.sheet_sync import sync_qualified_lead_to_google_sheet

        sync_qualified_lead_to_google_sheet(
            deal.lead,
            reason_code="check_pending_not_connected",
            config_user=owner_id,
        )
