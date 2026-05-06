# linkedin/tasks/send_message.py
"""Send Message task — dispatches approved HITL drafted messages via Playwright."""
from __future__ import annotations

import logging

from termcolor import colored

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.models import ActionLog
from chat.models import ChatMessage

logger = logging.getLogger(__name__)


def handle_send_message(task, session, qualifiers=None):
    from linkedin.actions.message import send_raw_message
    from django.utils import timezone
    from linkedin.tasks.connect import enqueue_follow_up, enqueue_reply_check

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]
    message_id = payload["message_id"]

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 send_message", "blue", attrs=["bold"]), public_id,
    )

    try:
        msg = ChatMessage.objects.get(pk=message_id)
    except ChatMessage.DoesNotExist:
        error_msg = f"send_message: ChatMessage {message_id} no longer exists — aborting"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    profile_dict = get_profile_dict_for_public_id(session, public_id)
    if profile_dict is None:
        raise RuntimeError(f"No Deal found for {public_id}")

    profile = profile_dict.get("profile") or profile_dict
    profile.setdefault("public_identifier", public_id)

    # Send path requires an active Playwright page; initialize browser explicitly.
    session.ensure_browser()
    if not session.page:
        raise RuntimeError("Cannot send message: browser page is unavailable.")

    logger.info("[%s] Dispatching approved message for %s...", session.campaign, public_id)
    sent = send_raw_message(session, profile, msg.content)
    
    if not sent:
        raise RuntimeError("LinkedIn blocked the message delivery (UI failed).")

    # Assuming success, remove draft suffix if it exists, record rate limit actions
    sent_at = timezone.now()
    if msg.linkedin_urn.startswith("draft_"):
        msg.linkedin_urn = msg.linkedin_urn.replace("draft_", "sent_")
    msg.creation_date = sent_at
    msg.is_draft = False
    msg.is_approved = True
    msg.save(update_fields=["linkedin_urn", "creation_date", "is_draft", "is_approved"])

    name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip() or public_id
    session.linkedin_profile.record_action(
        ActionLog.ActionType.FOLLOW_UP, 
        session.campaign,
        target_name=name,
        target_public_id=public_id,
        status="success",
        note=f"Message: {msg.content[:50]}..."
    )
    
    from crm.models.deal import Deal
    deal = Deal.objects.filter(lead__public_identifier=public_id, campaign_id=campaign_id).first()
    enqueue_follow_up(campaign_id, public_id, delay_seconds=4 * 3600, deal=deal)
    enqueue_reply_check(
        campaign_id,
        public_id,
        sent_message_id=msg.pk,
        sent_at=sent_at,
        deal=deal,
    )
    logger.info("Message dispatched successfully. Reply checks scheduled before ~4h follow-up.")
