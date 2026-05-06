from __future__ import annotations

from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from chat.models import ChatMessage
from crm.models import Deal, Lead
from linkedin.enums import ProfileState
from linkedin.models import Task


@dataclass
class ReplyBackfillResult:
    deal_id: int
    public_id: str
    status: str
    reason: str = ""
    changed: bool = False


def _lead_content_type():
    return ContentType.objects.get_for_model(Lead)


def _latest_real_message(lead: Lead, *, is_outgoing: bool) -> ChatMessage | None:
    return (
        ChatMessage.objects.filter(
            content_type=_lead_content_type(),
            object_id=lead.pk,
            is_draft=False,
            is_outgoing=is_outgoing,
        )
        .exclude(linkedin_urn__startswith="draft_")
        .order_by("-creation_date", "-id")
        .first()
    )


def has_reply_after_last_outgoing(lead: Lead) -> bool:
    latest_inbound = _latest_real_message(lead, is_outgoing=False)
    if latest_inbound is None:
        return False

    latest_outgoing = _latest_real_message(lead, is_outgoing=True)
    if latest_outgoing is None:
        return False

    return latest_inbound.creation_date > latest_outgoing.creation_date


def has_blocking_message_work(lead: Lead, campaign_id: int) -> bool:
    lead_ct = _lead_content_type()
    if ChatMessage.objects.filter(
        content_type=lead_ct,
        object_id=lead.pk,
        campaign_id=campaign_id,
        is_draft=True,
    ).exists():
        return True

    return Task.objects.filter(
        task_type=Task.TaskType.SEND_MESSAGE,
        status__in=[Task.Status.PENDING, Task.Status.RUNNING],
        payload__campaign_id=campaign_id,
        payload__public_id=lead.public_identifier,
    ).exists()


def accelerate_or_enqueue_follow_up(deal: Deal, *, dry_run: bool = False) -> bool:
    if dry_run:
        return True

    Task.objects.filter(
        task_type=Task.TaskType.REPLY_CHECK,
        status=Task.Status.PENDING,
        payload__campaign_id=deal.campaign_id,
        payload__public_id=deal.lead.public_identifier,
    ).delete()

    pending = Task.objects.filter(
        task_type=Task.TaskType.FOLLOW_UP,
        status=Task.Status.PENDING,
        payload__campaign_id=deal.campaign_id,
        payload__public_id=deal.lead.public_identifier,
    )
    if pending.exists():
        pending.update(scheduled_at=timezone.now(), deal=deal)
        return True

    from linkedin.tasks.connect import enqueue_follow_up

    enqueue_follow_up(
        deal.campaign_id,
        deal.lead.public_identifier,
        delay_seconds=0,
        deal=deal,
    )
    return True


def process_replied_deal(deal: Deal, session, *, dry_run: bool = False) -> ReplyBackfillResult:
    from linkedin.db.chat import sync_conversation

    lead = deal.lead
    public_id = lead.public_identifier if lead else ""
    if not lead or not public_id:
        return ReplyBackfillResult(deal.pk, public_id, "skipped", "missing lead/public_id")
    if deal.state != ProfileState.CONNECTED.value:
        return ReplyBackfillResult(deal.pk, public_id, "skipped", f"deal is {deal.state}")
    if has_blocking_message_work(lead, deal.campaign_id):
        return ReplyBackfillResult(deal.pk, public_id, "skipped", "draft/send task already exists")

    session.campaign = deal.campaign
    sync_conversation(session, public_id, include_drafts=False)

    if not has_reply_after_last_outgoing(lead):
        return ReplyBackfillResult(deal.pk, public_id, "skipped", "no inbound reply after last outgoing")

    accelerate_or_enqueue_follow_up(deal, dry_run=dry_run)
    return ReplyBackfillResult(
        deal.pk,
        public_id,
        "accelerated" if not dry_run else "would_accelerate",
        changed=True,
    )
