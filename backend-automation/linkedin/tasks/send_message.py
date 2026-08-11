# linkedin/tasks/send_message.py
"""Send Message task — dispatches approved HITL drafted messages via Playwright."""
from __future__ import annotations

import logging
from datetime import timedelta

from termcolor import colored
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.exceptions import TaskSkipped
from linkedin.models import ActionLog
from chat.models import ChatMessage

logger = logging.getLogger(__name__)


def handle_send_message(task, session, qualifiers=None):
    from linkedin.actions.message import send_raw_message
    from django.utils import timezone
    from linkedin.tasks.connect import enqueue_follow_up, enqueue_reply_check
    from crm.models.deal import Deal
    from linkedin.models import OutreachEvent
    from linkedin.outreach_tracking import emit_outreach_event

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

    instagram_profile = getattr(session, "instagram_profile", None)
    instagram_profile_id = instagram_profile.pk if getattr(instagram_profile, "pk", None) is not None else None
    try:
        msg = ChatMessage.objects.get(pk=message_id, instagram_profile=instagram_profile)
    except ChatMessage.DoesNotExist:
        error_msg = f"send_message: ChatMessage {message_id} is not available for this Instagram profile — aborting"
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
        if instagram_profile_id is not None:
            payload["instagram_profile_id"] = instagram_profile_id
        current_task_pk = getattr(task, "pk", None)
        if not isinstance(current_task_pk, int):
            current_task_pk = None
        exists_qs = Task.objects.filter(
            task_type=Task.TaskType.SEND_MESSAGE,
            status__in=[Task.Status.PENDING, Task.Status.RUNNING],
            payload__campaign_id=campaign_id,
            payload__public_id=public_id,
            payload__message_id=message_id,
        )
        if instagram_profile_id is not None:
            exists_qs = exists_qs.filter(payload__instagram_profile_id=instagram_profile_id)
        exists = exists_qs.exclude(pk=current_task_pk).exists()
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
        from linkedin.db.deals import set_profile_state
        from linkedin.enums import ProfileState
        from linkedin.models import OutreachEvent
        from linkedin.outreach_tracking import emit_outreach_event

        reason = str(skip_exc)
        fail_reason = (
            "Instagram Message button not available "
            "(private/restricted account or Message UI missing) — not falling back to Follow"
        )
        if deal:
            set_profile_state(
                session,
                public_id,
                ProfileState.FAILED.value,
                reason=fail_reason,
            )
            emit_outreach_event(
                OutreachEvent.EventType.MESSAGE_FAILED,
                deal=deal,
                lead=deal.lead,
                campaign=session.campaign,
                public_id=public_id,
                metadata={"reason": reason[:500], "via": "send_message_not_messageable"},
            )
        raise TaskSkipped(fail_reason) from skip_exc

    def _send_once():
        # Send path requires an active Playwright page; initialize browser explicitly.
        session.ensure_browser()
        if not session.page:
            raise RuntimeError("Cannot send message: browser page is unavailable.")

        logger.info("[%s] Dispatching approved message for %s via profile UI...", session.campaign, public_id)
        return send_raw_message(session, profile, msg.content)

    def _is_transient_playwright_timeout(exc: Exception) -> bool:
        text = str(exc)
        return (
            isinstance(exc, PlaywrightTimeoutError)
            or "Timeout" in exc.__class__.__name__
            or "Timeout" in text
            or "Page.goto" in text
        )

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
            if _is_transient_playwright_timeout(exc):
                _requeue_approved_send(10 * 60, f"Transient Instagram timeout during send: {exc}")
                raise TaskSkipped(
                    "Instagram timed out during approved DM send; message requeued"
                ) from exc
            raise
        logger.warning("Browser closed during send for %s - relaunching once", public_id)
        session.close()
        sent = _send_once()
    
    if not sent:
        _requeue_approved_send(
            30 * 60,
            "Profile Message popup send failed; approved message retained for retry",
        )
        raise TaskSkipped("Instagram DM send failed; approved message requeued")

    # Assuming success, remove draft suffix if it exists, record rate limit actions
    sent_at = timezone.now()
    if msg.instagram_message_id.startswith("draft_"):
        msg.instagram_message_id = msg.instagram_message_id.replace("draft_", "sent_")
    msg.creation_date = sent_at
    msg.is_draft = False
    msg.is_approved = True
    msg.save(update_fields=["instagram_message_id", "creation_date", "is_draft", "is_approved"])

    name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip() or public_id
    session.instagram_profile.record_action(
        ActionLog.ActionType.FOLLOW_UP, 
        session.campaign,
        target_name=name,
        target_public_id=public_id,
        status="success",
        note=f"Message: {msg.content[:50]}..."
    )

    if deal:
        emit_outreach_event(
            OutreachEvent.EventType.MESSAGE_SENT,
            deal=deal,
            lead=deal.lead,
            campaign=session.campaign,
            public_id=public_id,
            metadata={"message_id": msg.pk, "via": "send_message"},
        )
        if deal.lead_id:
            from google_integration.sheet_sync import sync_messaged_lead_to_google_sheet

            sync_messaged_lead_to_google_sheet(deal.lead, config_user=owner_id)

    enqueue_follow_up(
        campaign_id,
        public_id,
        delay_seconds=4 * 3600,
        deal=deal,
        owner_id=owner_id,
        instagram_profile_id=instagram_profile_id,
        apply_time_limits=False,
    )
    enqueue_reply_check(
        campaign_id,
        public_id,
        sent_message_id=msg.pk,
        sent_at=sent_at,
        deal=deal,
        owner_id=owner_id,
        instagram_profile_id=instagram_profile_id,
    )
    logger.info("Message dispatched successfully. Reply checks scheduled before ~4h follow-up.")
