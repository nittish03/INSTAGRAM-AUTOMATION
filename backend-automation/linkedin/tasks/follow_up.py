# linkedin/tasks/follow_up.py
"""Follow-up task — runs the agentic follow-up for one CONNECTED profile.

HITL mode: when the agent suggests ``send_message``, we store a draft in
``ChatMessage`` and wait for admin approval. Admin action ``approve_and_send``
creates the ``send_message`` task.
"""
from __future__ import annotations

import logging
import uuid

from termcolor import colored

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.models import ActionLog
from linkedin.exceptions import TaskSkipped

logger = logging.getLogger(__name__)


def handle_follow_up(task, session, qualifiers):
    from chat.models import ChatMessage
    from crm.models import Lead
    from crm.models.deal import Deal
    from django.contrib.contenttypes.models import ContentType

    from linkedin.agents.follow_up import run_follow_up_agent
    from linkedin.db.deals import set_profile_state
    from linkedin.enums import ProfileState
    from linkedin.tasks.connect import _seconds_until_tomorrow, enqueue_follow_up

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 follow_up", "green", attrs=["bold"]), public_id,
    )

    if not session.linkedin_profile.can_execute(ActionLog.ActionType.FOLLOW_UP):
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        enqueue_follow_up(campaign_id, public_id, delay_seconds=_seconds_until_tomorrow(), deal=deal)
        raise TaskSkipped("Daily follow-up limit reached")

    profile_dict = get_profile_dict_for_public_id(session, public_id)
    if profile_dict is None:
        error_msg = f"follow_up: no Deal for {public_id} — aborting"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    profile = profile_dict.get("profile") or profile_dict

    decision = run_follow_up_agent(session, public_id, profile)

    if decision.action == "send_message":
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        if not deal:
            logger.warning("follow_up: drafted message but no Deal — skipping draft for %s", public_id)
            return

        lead_ct = ContentType.objects.get_for_model(Lead)
        has_draft = ChatMessage.objects.filter(
            content_type=lead_ct,
            object_id=deal.lead.pk,
            is_draft=True,
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
                owner=session.linkedin_profile.user,
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
        enqueue_follow_up(campaign_id, public_id, delay_seconds=wait_hours * 3600, deal=deal)
