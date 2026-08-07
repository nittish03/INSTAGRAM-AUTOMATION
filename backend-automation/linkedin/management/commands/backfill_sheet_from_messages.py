"""Backfill Google Sheet rows for CONNECTED leads that already received outbound messages."""

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from crm.models import Deal, Lead
from google_integration.sheet_sync import sync_messaged_lead_to_google_sheet
from linkedin.enums import ProfileState
from linkedin.models import ActionLog


class Command(BaseCommand):
    help = (
        "Upsert sheet rows for CONNECTED leads with a successful FOLLOW_UP ActionLog "
        "(no CONNECTION_DETECTED verification required)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List candidate leads without writing to the sheet.",
        )
        parser.add_argument(
            "--include-exported",
            action="store_true",
            help="Include leads that already have sheet_exported_at set.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        include_exported = bool(options["include_exported"])

        follow_up_exists = ActionLog.objects.filter(
            target_public_id=OuterRef("public_identifier"),
            action_type=ActionLog.ActionType.FOLLOW_UP,
            status=ActionLog.Status.SUCCESS,
        )
        connected_deal_exists = Deal.objects.filter(
            lead_id=OuterRef("pk"),
            state=ProfileState.CONNECTED,
        )

        qs = (
            Lead.objects.annotate(
                has_follow_up=Exists(follow_up_exists),
                has_connected=Exists(connected_deal_exists),
            )
            .filter(
                has_follow_up=True,
                has_connected=True,
            )
            .exclude(linkedin_url="")
            .exclude(public_identifier="")
            .order_by("pk")
        )
        if not include_exported:
            qs = qs.filter(sheet_exported_at__isnull=True)

        exported = 0
        skipped = 0
        for lead in qs.iterator(chunk_size=200):
            if dry_run:
                self.stdout.write(f"Would sync: {lead.public_identifier} (pk={lead.pk})")
                exported += 1
                continue
            if sync_messaged_lead_to_google_sheet(lead, reason_code="backfill_message"):
                exported += 1
            else:
                skipped += 1

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: {exported} candidate lead(s) would be synced.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Backfill complete: exported={exported} skipped={skipped}")
            )
