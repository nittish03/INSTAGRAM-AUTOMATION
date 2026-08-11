# linkedin/tasks/reply_check.py
"""Reply-check task - polls active conversations cheaply before no-reply follow-up."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from termcolor import colored

from chat.models import ChatMessage
from crm.models import Deal, Lead
from linkedin.conf import bot_time_limits_enabled
from linkedin.enums import ProfileState
from linkedin.models import Task

logger = logging.getLogger(__name__)


def _parse_payload_datetime(value: str | None):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _has_pending_draft(lead: Lead, *, campaign_id: int, owner, instagram_profile) -> bool:
    lead_ct = ContentType.objects.get_for_model(Lead)
    return ChatMessage.objects.filter(
        content_type=lead_ct,
        object_id=lead.pk,
        campaign_id=campaign_id,
        owner=owner,
        instagram_profile=instagram_profile,
        is_draft=True,
        is_approved=False,
    ).exists()


def _latest_inbound_after(lead: Lead, sent_at, *, owner, instagram_profile, before=None):
    lead_ct = ContentType.objects.get_for_model(Lead)
    messages = ChatMessage.objects.filter(
        content_type=lead_ct,
        object_id=lead.pk,
        owner=owner,
        instagram_profile=instagram_profile,
        is_outgoing=False,
        is_draft=False,
        creation_date__gt=sent_at,
    )
    if before:
        messages = messages.filter(creation_date__lte=before)
    return (
        messages
        .order_by("-creation_date")
        .first()
    )


def _accelerate_follow_up(
    campaign_id: int,
    public_id: str,
    deal: Deal | None,
    *,
    owner_id: int | None,
    instagram_profile_id: int | None,
) -> None:
    now = timezone.now()
    (
        Task.objects.filter(
            task_type=Task.TaskType.REPLY_CHECK,
            status=Task.Status.PENDING,
            payload__campaign_id=campaign_id,
            payload__public_id=public_id,
        )
        .filter(Q(payload__owner_id=owner_id) | Q(payload__owner_id__isnull=True))
        .filter(Q(payload__instagram_profile_id=instagram_profile_id) | Q(payload__instagram_profile_id__isnull=True))
        .delete()
    )
    pending = Task.objects.filter(
        task_type=Task.TaskType.FOLLOW_UP,
        status=Task.Status.PENDING,
        payload__campaign_id=campaign_id,
        payload__public_id=public_id,
    ).filter(
        Q(payload__owner_id=owner_id) | Q(payload__owner_id__isnull=True),
        Q(payload__instagram_profile_id=instagram_profile_id) | Q(payload__instagram_profile_id__isnull=True),
    )
    if pending.exists():
        pending.update(scheduled_at=now, deal=deal)
        return

    from linkedin.tasks.connect import enqueue_follow_up

    enqueue_follow_up(
        campaign_id,
        public_id,
        delay_seconds=0,
        deal=deal,
        owner_id=owner_id,
        instagram_profile_id=instagram_profile_id,
    )


def _normal_follow_up_due_before(
    campaign_id: int,
    public_id: str,
    next_check_at,
    *,
    owner_id: int | None,
    instagram_profile_id: int | None,
) -> bool:
    return Task.objects.filter(
        task_type=Task.TaskType.FOLLOW_UP,
        status=Task.Status.PENDING,
        payload__campaign_id=campaign_id,
        payload__public_id=public_id,
        scheduled_at__lte=next_check_at,
    ).filter(
        Q(payload__owner_id=owner_id) | Q(payload__owner_id__isnull=True),
        Q(payload__instagram_profile_id=instagram_profile_id) | Q(payload__instagram_profile_id__isnull=True),
    ).exists()


def handle_reply_check(task, session, qualifiers=None):
    from linkedin.db.chat import sync_conversation
    from linkedin.tasks.connect import enqueue_reply_check

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]
    attempt = int(payload.get("attempt") or 1)
    max_attempts = int(payload.get("max_attempts") or 12)
    interval_seconds = float(payload.get("interval_seconds") or 10 * 60)
    sent_message_id = payload.get("sent_message_id")
    owner = session.django_user
    owner_id = getattr(owner, "pk", None)
    instagram_profile = getattr(session, "instagram_profile", None)
    instagram_profile_id = getattr(instagram_profile, "pk", None)
    sent_at = _parse_payload_datetime(payload.get("sent_at")) or timezone.now()
    expires_at = _parse_payload_datetime(payload.get("expires_at"))
    now = timezone.now()
    enforce_time_limits = bot_time_limits_enabled()

    logger.info(
        "[%s] %s %s attempt=%s/%s",
        session.campaign,
        colored("reply_check", "yellow", attrs=["bold"]),
        public_id,
        attempt,
        max_attempts,
    )

    deal = Deal.objects.filter(
        lead__public_identifier=public_id,
        campaign_id=campaign_id,
    ).select_related("lead").first()
    if not deal or not deal.lead:
        logger.info("reply_check: no Deal found for %s - stopping watcher", public_id)
        return
    # DM-first: reply watching continues after send for Qualified or Connected deals.
    if deal.state not in (ProfileState.QUALIFIED.value, ProfileState.CONNECTED.value):
        logger.info("reply_check: %s is %s - stopping watcher", public_id, deal.state)
        return
    if _has_pending_draft(
        deal.lead,
        campaign_id=campaign_id,
        owner=owner,
        instagram_profile=instagram_profile,
    ):
        logger.info("reply_check: draft already exists for %s - stopping watcher", public_id)
        return
    if enforce_time_limits and expires_at and now >= expires_at:
        logger.info("reply_check: active reply window expired for %s - stopping watcher", public_id)
        return

    sync_conversation(session, public_id, include_drafts=False)

    inbound = _latest_inbound_after(
        deal.lead,
        sent_at,
        owner=owner,
        instagram_profile=instagram_profile,
        before=expires_at,
    )
    if inbound:
        logger.info(
            "reply_check: inbound reply detected for %s at %s - follow-up moved to now",
            public_id,
            inbound.creation_date,
        )
        _accelerate_follow_up(
            campaign_id,
            public_id,
            deal,
            owner_id=owner_id,
            instagram_profile_id=instagram_profile_id,
        )
        return

    next_attempt = attempt + 1
    next_check_at = now + timedelta(seconds=interval_seconds)
    if enforce_time_limits and next_attempt > max_attempts:
        logger.info("reply_check: max attempts reached for %s - stopping watcher", public_id)
        return
    if enforce_time_limits and expires_at and next_check_at > expires_at:
        logger.info("reply_check: active reply window expired for %s - stopping watcher", public_id)
        return
    if _normal_follow_up_due_before(
        campaign_id,
        public_id,
        next_check_at,
        owner_id=owner_id,
        instagram_profile_id=instagram_profile_id,
    ):
        logger.info("reply_check: normal follow-up is due before next check for %s", public_id)
        return

    enqueue_reply_check(
        campaign_id,
        public_id,
        sent_message_id=sent_message_id,
        sent_at=sent_at,
        attempt=next_attempt,
        interval_seconds=interval_seconds,
        max_attempts=max_attempts,
        window_seconds=(expires_at - sent_at).total_seconds() if expires_at else None,
        delay_seconds=interval_seconds,
        deal=deal,
        owner_id=owner_id,
        instagram_profile_id=instagram_profile_id,
    )
