"""CRM signals — Google Sheet export after lead saves."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from crm.models.lead import Lead

logger = logging.getLogger(__name__)


def _sync_lead_after_commit(lead_pk: int) -> None:
    lead = Lead.objects.filter(pk=lead_pk).first()
    if not lead or lead.sheet_exported_at is not None:
        return
    if lead.profile_data is None:
        return
    from google_integration.sheet_sync import sync_lead_to_google_sheet

    sync_lead_to_google_sheet(lead)


@receiver(post_save, sender=Lead)
def lead_post_save_google_sheet(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    if instance.sheet_exported_at is not None:
        return
    transaction.on_commit(lambda pk=instance.pk: _sync_lead_after_commit(pk))
