"""CRM signals — Google Sheet export only after a Deal hits CONNECTED.

We sync on Deal save (not Lead save) because a Lead row exists from discovery
onward; the user only cares about prospects who accepted the connection.
"""
from __future__ import annotations

import logging

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
