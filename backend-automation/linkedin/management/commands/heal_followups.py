"""Re-enqueue follow_up tasks for every CONNECTED Deal that has no draft / send_message task.

Run this once after pulling the messaging fix to backfill any leads that connected before
the auto-enqueue signal was added. Safe to run repeatedly (idempotent dedup).
"""
from __future__ import annotations

import random

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill follow_up tasks for CONNECTED leads missing drafts."

    def handle(self, *args, **options):
        from chat.models import ChatMessage
        from crm.models import Deal
        from django.contrib.contenttypes.models import ContentType
        from linkedin.enums import ProfileState
        from linkedin.models import Task
        from linkedin.tasks.connect import enqueue_follow_up

        deals = (
            Deal.objects.filter(state=ProfileState.CONNECTED)
            .select_related("lead", "campaign")
        )

        if not deals.exists():
            self.stdout.write("No CONNECTED deals — nothing to heal.")
            return

        enqueued = 0
        skipped = 0

        for deal in deals:
            lead = deal.lead
            if not lead or not lead.public_identifier:
                skipped += 1
                continue

            lead_ct = ContentType.objects.get_for_model(lead.__class__)
            has_draft = ChatMessage.objects.filter(
                content_type=lead_ct,
                object_id=lead.pk,
                is_draft=True,
            ).exists()
            has_pending_followup = Task.objects.filter(
                task_type=Task.TaskType.FOLLOW_UP,
                status=Task.Status.PENDING,
                payload__public_id=lead.public_identifier,
            ).exists()
            has_send_task = Task.objects.filter(
                task_type=Task.TaskType.SEND_MESSAGE,
                status__in=[Task.Status.PENDING, Task.Status.RUNNING],
                payload__public_id=lead.public_identifier,
            ).exists()

            if has_draft or has_pending_followup or has_send_task:
                skipped += 1
                continue

            enqueue_follow_up(
                deal.campaign_id,
                lead.public_identifier,
                delay_seconds=random.uniform(5, 30),
                deal=deal,
            )
            enqueued += 1

        self.stdout.write(self.style.SUCCESS(
            f"Heal complete: enqueued {enqueued} follow_up task(s), "
            f"skipped {skipped} (already drafted / queued)."
        ))
