# linkedin/tasks/follow_up.py
"""Follow-up task — runs the agentic follow-up for one CONNECTED profile.

HITL mode: when the agent suggests ``send_message``, we store a draft only in
``ChatMessage`` and wait for admin approval. Nothing is typed into LinkedIn
until approval creates the ``send_message`` task.
"""
from __future__ import annotations

import logging
import re
import uuid

from termcolor import colored

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.models import ActionLog
from linkedin.exceptions import TaskSkipped

logger = logging.getLogger(__name__)


def _quota_retry_delay_seconds(exc: Exception) -> int | None:
    message = str(exc)
    if "RESOURCE_EXHAUSTED" not in message and "429" not in message:
        return None
    if "generate_content_free_tier_requests" not in message and "quota" not in message.lower():
        return None
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", message, flags=re.IGNORECASE)
    retry_after = float(match.group(1)) if match else 60.0
    # The provider retry hint can be only seconds even when the free-tier
    # bucket is saturated. Use a longer floor so the daemon does not hammer
    # Gemini and turn every follow-up into repeated failures.
    return max(30 * 60, int(retry_after) + 15)


def handle_follow_up(task, session, qualifiers):
    from chat.models import ChatMessage
    from crm.models import Lead
    from crm.models.deal import Deal
    from django.contrib.contenttypes.models import ContentType

    from linkedin.agents.follow_up import run_follow_up_agent
    from linkedin.actions.status import get_connection_assessment
    from linkedin.db.deals import set_profile_state
    from linkedin.enums import ProfileState
    from linkedin.outreach_tracking import update_deal_inference
    from linkedin.tasks.connect import _seconds_until_tomorrow, enqueue_check_pending, enqueue_follow_up

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]
    owner = session.linkedin_profile.user
    owner_id = owner.pk

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 follow_up", "green", attrs=["bold"]), public_id,
    )

    if not session.linkedin_profile.can_execute(ActionLog.ActionType.FOLLOW_UP):
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        enqueue_follow_up(
            campaign_id,
            public_id,
            delay_seconds=_seconds_until_tomorrow(),
            deal=deal,
            owner_id=owner_id,
        )
        raise TaskSkipped("Daily follow-up limit reached")

    profile_dict = get_profile_dict_for_public_id(session, public_id)
    if profile_dict is None:
        error_msg = f"follow_up: no Deal for {public_id} — aborting"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    profile = profile_dict.get("profile") or profile_dict
    deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
    if not deal:
        logger.warning("follow_up: no Deal for %s — skipping draft", public_id)
        return

    assessment = get_connection_assessment(session, profile)
    update_deal_inference(deal, assessment.source, assessment.confidence)
    verified_connected = (
        assessment.state == ProfileState.CONNECTED
        and assessment.source == "api_degree_1"
    )
    if not verified_connected:
        state_to_store = (
            ProfileState.PENDING
            if assessment.state == ProfileState.CONNECTED
            else assessment.state
        )
        set_profile_state(session, public_id, state_to_store.value)
        if state_to_store == ProfileState.PENDING:
            enqueue_check_pending(
                campaign_id,
                public_id,
                backoff_hours=deal.backoff_hours or 6,
                deal=deal,
                owner_id=owner_id,
            )
        raise TaskSkipped(
            "follow_up requires an API-verified connected profile before drafting "
            f"(source={assessment.source}, state={assessment.state.value})"
        )

    try:
        decision = run_follow_up_agent(session, public_id, profile)
    except Exception as exc:
        retry_delay = _quota_retry_delay_seconds(exc)
        if retry_delay is None:
            raise
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        enqueue_follow_up(
            campaign_id,
            public_id,
            delay_seconds=retry_delay,
            deal=deal,
            owner_id=owner_id,
        )
        raise TaskSkipped(f"Gemini quota exhausted; follow_up rescheduled in {retry_delay}s") from exc

    if decision.action == "send_message":
        lead_ct = ContentType.objects.get_for_model(Lead)
        has_draft = ChatMessage.objects.filter(
            content_type=lead_ct,
            object_id=deal.lead.pk,
            campaign=deal.campaign,
            owner=owner,
            is_draft=True,
            is_approved=False,
        ).exists()
        if has_draft:
            logger.info("[%s] follow_up: draft already exists for %s — skipping", session.campaign, public_id)
        else:
            ChatMessage.objects.create(
                content_type=lead_ct,
                object_id=deal.lead.pk,
                campaign=deal.campaign,
                content=decision.message,
                is_outgoing=True,
                is_draft=True,
                is_approved=False,
                owner=owner,
                linkedin_urn=f"draft_{uuid.uuid4()}",
            )
            logger.info(
                "[%s] follow_up drafted message for %s (awaiting admin approval)",
                session.campaign,
                public_id,
            )

    elif decision.action == "mark_completed":
        set_profile_state(session, public_id, ProfileState.COMPLETED.value, reason=decision.reason)

    elif decision.action == "wait":
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        wait_hours = max(0.5, float(decision.follow_up_hours or 4))
        enqueue_follow_up(
            campaign_id,
            public_id,
            delay_seconds=wait_hours * 3600,
            deal=deal,
            owner_id=owner_id,
        )
