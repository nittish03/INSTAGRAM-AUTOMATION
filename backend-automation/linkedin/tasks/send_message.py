# linkedin/tasks/send_message.py
"""Send Message task — dispatches approved HITL drafted messages via Playwright."""
from __future__ import annotations

import logging
from datetime import timedelta

from termcolor import colored

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.exceptions import TaskSkipped
from linkedin.models import ActionLog
from chat.models import ChatMessage

logger = logging.getLogger(__name__)


def handle_send_message(task, session, qualifiers=None):
    from linkedin.actions.message import send_raw_message
    from django.utils import timezone
    from linkedin.tasks.connect import enqueue_check_pending, enqueue_follow_up, enqueue_reply_check
    from crm.models.deal import Deal

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]
    message_id = payload["message_id"]
    owner_id = payload.get("owner_id") or getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(owner_id, int):
        owner_id = None

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
    deal = Deal.objects.filter(lead__public_identifier=public_id, campaign_id=campaign_id).select_related("lead").first()

    def _requeue_approved_send(delay_seconds: float, reason: str) -> None:
        from linkedin.models import Task

        payload = {
            "campaign_id": campaign_id,
            "public_id": public_id,
            "message_id": message_id,
        }
        if owner_id is not None:
            payload["owner_id"] = owner_id
        current_task_pk = getattr(task, "pk", None)
        if not isinstance(current_task_pk, int):
            current_task_pk = None
        exists = Task.objects.filter(
            task_type=Task.TaskType.SEND_MESSAGE,
            status__in=[Task.Status.PENDING, Task.Status.RUNNING],
            payload__campaign_id=campaign_id,
            payload__public_id=public_id,
            payload__message_id=message_id,
        ).exclude(pk=current_task_pk).exists()
        if exists:
            return
        Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            status=Task.Status.PENDING,
            scheduled_at=timezone.now() + timedelta(seconds=delay_seconds),
            payload=payload,
            deal=deal,
            error=reason[:1000],
        )

    def _handle_not_messageable(skip_exc: TaskSkipped) -> None:
        from linkedin.actions.connect import send_connection_request
        from linkedin.conf import CAMPAIGN_CONFIG
        from linkedin.db.deals import set_profile_state
        from linkedin.enums import ProfileState
        from linkedin.models import ActionLog, OutreachEvent
        from linkedin.outreach_tracking import emit_outreach_event

        reason = str(skip_exc)
        backoff_hours = float(CAMPAIGN_CONFIG["check_pending_recheck_after_hours"])
        retry_delay = backoff_hours * 3600

        if "Pending" in reason:
            if deal:
                enqueue_check_pending(campaign_id, public_id, backoff_hours=backoff_hours, deal=deal, owner_id=owner_id)
            _requeue_approved_send(retry_delay, "Waiting for pending connection before sending approved message")
            raise TaskSkipped("LinkedIn still shows Pending; approved message will retry after connection check") from skip_exc

        if "Connect" not in reason:
            raise skip_exc

        if not session.linkedin_profile.can_execute(ActionLog.ActionType.CONNECT):
            _requeue_approved_send(24 * 3600, "Connect limit reached before approved message could be sent")
            raise TaskSkipped("LinkedIn shows Connect but connect limit is reached; approved message requeued") from skip_exc

        new_state = send_connection_request(session=session, profile=profile)
        set_profile_state(session, public_id, new_state.value)

        name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip() or public_id
        session.linkedin_profile.record_action(
            ActionLog.ActionType.CONNECT,
            session.campaign,
            target_name=name,
            target_public_id=public_id,
            status="success" if new_state in (ProfileState.PENDING, ProfileState.CONNECTED) else "failed",
            note="Auto-connect before sending approved message",
        )

        if new_state == ProfileState.PENDING:
            if deal:
                emit_outreach_event(
                    OutreachEvent.EventType.INVITE_SENT,
                    deal=deal,
                    lead=deal.lead,
                    campaign=session.campaign,
                    public_id=public_id,
                    metadata={"via": "send_message_not_connected"},
                )
                if deal.lead_id:
                    from google_integration.sheet_sync import sync_pending_lead_to_google_sheet

                    sync_pending_lead_to_google_sheet(deal.lead, reason_code="send_message_auto_connect")
                enqueue_check_pending(campaign_id, public_id, backoff_hours=backoff_hours, deal=deal, owner_id=owner_id)
            _requeue_approved_send(retry_delay, "Connection invite sent before approved message could be delivered")
            raise TaskSkipped("LinkedIn showed Connect; sent connection invite and requeued approved message") from skip_exc

        if new_state == ProfileState.CONNECTED:
            _requeue_approved_send(60, "Connected during send_message; retrying approved message")
            raise TaskSkipped("Connected during send_message; approved message requeued") from skip_exc

        _requeue_approved_send(retry_delay, f"Connect attempt returned {new_state.value}; approved message retained")
        raise TaskSkipped(f"LinkedIn showed Connect; connect attempt returned {new_state.value}") from skip_exc

    def _send_once():
        # Send path requires an active Playwright page; initialize browser explicitly.
        session.ensure_browser()
        if not session.page:
            raise RuntimeError("Cannot send message: browser page is unavailable.")

        logger.info("[%s] Dispatching approved message for %s via profile UI...", session.campaign, public_id)
        return send_raw_message(session, profile, msg.content)

    try:
        sent = _send_once()
    except TaskSkipped as exc:
        _handle_not_messageable(exc)
    except Exception as exc:
        is_closed_page = (
            exc.__class__.__name__ == "TargetClosedError"
            or "Target page, context or browser has been closed" in str(exc)
        )
        if not is_closed_page:
            raise
        logger.warning("Browser closed during send for %s - relaunching once", public_id)
        session.close()
        sent = _send_once()
    
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
    
    enqueue_follow_up(campaign_id, public_id, delay_seconds=4 * 3600, deal=deal, owner_id=owner_id)
    enqueue_reply_check(
        campaign_id,
        public_id,
        sent_message_id=msg.pk,
        sent_at=sent_at,
        deal=deal,
        owner_id=owner_id,
    )
    logger.info("Message dispatched successfully. Reply checks scheduled before ~4h follow-up.")
