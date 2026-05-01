"""CRM signals — Google Sheet export and follow-up enqueue when a Deal hits CONNECTED.

We sync on Deal save (not Lead save) because a Lead row exists from discovery
onward; the user only cares about prospects who accepted the connection.
"""
from __future__ import annotations

import logging
import random

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from crm.models.deal import Deal
from linkedin.enums import ProfileState

logger = logging.getLogger(__name__)


def _sync_lead_after_commit(lead_pk: int) -> None:
    from crm.models.lead import Lead
    from google_integration.sheet_sync import sync_lead_to_google_sheet

    lead = Lead.objects.filter(pk=lead_pk).first()
    if not lead or lead.sheet_exported_at is not None:
        return
    sync_lead_to_google_sheet(lead)


def _enqueue_follow_up_after_commit(deal_pk: int) -> None:
    """Ensure a FOLLOW_UP task exists for a CONNECTED Deal (idempotent).

    Skip if the lead already has a pending draft or a queued send_message task.
    """
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType
    from crm.models.deal import Deal as _Deal
    from linkedin.models import Task
    from linkedin.tasks.connect import enqueue_follow_up

    deal = (
        _Deal.objects.select_related("lead", "campaign")
        .filter(pk=deal_pk, state=ProfileState.CONNECTED)
        .first()
    )
    if not deal or not deal.lead or not deal.lead.public_identifier:
        return

    lead_ct = ContentType.objects.get_for_model(deal.lead.__class__)
    has_pending_draft = ChatMessage.objects.filter(
        content_type=lead_ct,
        object_id=deal.lead.pk,
        is_draft=True,
    ).exists()
    has_send_task = Task.objects.filter(
        task_type=Task.TaskType.SEND_MESSAGE,
        status__in=[Task.Status.PENDING, Task.Status.RUNNING],
        payload__public_id=deal.lead.public_identifier,
    ).exists()
    if has_pending_draft or has_send_task:
        return

    enqueue_follow_up(
        deal.campaign_id,
        deal.lead.public_identifier,
        delay_seconds=random.uniform(5, 60),
        deal=deal,
    )
    logger.info(
        "follow_up enqueued via signal for %s (deal=%s)",
        deal.lead.public_identifier,
        deal.pk,
    )


@receiver(pre_save, sender=Deal)
def deal_pre_save_track_state(sender, instance: Deal, **kwargs):
    """Cache previous state on the instance so post_save can detect transitions."""
    if not instance.pk:
        instance._previous_state = None
        return
    try:
        prev = Deal.objects.only("state").get(pk=instance.pk)
        instance._previous_state = prev.state
    except Deal.DoesNotExist:
        instance._previous_state = None


@receiver(post_save, sender=Deal)
def deal_post_save_google_sheet(sender, instance: Deal, created: bool, **kwargs):
    """Export the lead the first time its Deal becomes CONNECTED."""
    if kwargs.get("raw"):
        return

    new_state = instance.state
    if new_state != ProfileState.CONNECTED:
        return

    previous_state = getattr(instance, "_previous_state", None)
    if not created and previous_state == ProfileState.CONNECTED:
        return

    lead_id = instance.lead_id
    if not lead_id:
        return

    transaction.on_commit(lambda pk=lead_id: _sync_lead_after_commit(pk))
    transaction.on_commit(lambda pk=instance.pk: _enqueue_follow_up_after_commit(pk))
