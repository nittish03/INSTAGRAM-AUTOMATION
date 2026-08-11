from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync connected conversations and run replied leads through follow-up immediately."

    def add_arguments(self, parser):
        parser.add_argument(
            "--handle",
            default=None,
            help="Django username for the Instagram account to use. Defaults to first active profile.",
        )
        parser.add_argument(
            "--campaign-id",
            type=int,
            default=None,
            help="Only process deals from this campaign.",
        )
        parser.add_argument(
            "--public-id",
            default="",
            help="Only process one Instagram public identifier.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of connected deals to inspect.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Sync Instagram conversations and report what would be accelerated, "
                "but do not move or create follow-up tasks."
            ),
        )

    def handle(self, *args, **options):
        from crm.models import Deal
        from linkedin.browser.registry import get_or_create_session, resolve_profile
        from linkedin.enums import ProfileState
        from linkedin.services.reply_backfill import process_replied_deal

        instagram_profile = resolve_profile(options["handle"])
        if instagram_profile is None:
            raise CommandError("No active InstagramProfile found.")

        qs = (
            Deal.objects.filter(state=ProfileState.CONNECTED.value)
            .select_related("lead", "campaign")
            .order_by("id")
        )
        if options["campaign_id"]:
            qs = qs.filter(campaign_id=options["campaign_id"])
        if options["public_id"]:
            qs = qs.filter(lead__public_identifier=options["public_id"])
        if options["limit"] is not None:
            if options["limit"] < 1:
                raise CommandError("--limit must be positive")
            qs = qs[: options["limit"]]

        deals = list(qs)
        if not deals:
            self.stdout.write("No matching CONNECTED deals found.")
            return

        session = get_or_create_session(instagram_profile)
        accelerated = skipped = failed = 0
        try:
            for deal in deals:
                try:
                    result = process_replied_deal(
                        deal,
                        session,
                        dry_run=options["dry_run"],
                    )
                except Exception as exc:
                    failed += 1
                    logger.exception("Failed to process replies for deal %s", deal.pk)
                    self.stderr.write(
                        f"FAILED deal={deal.pk} public_id={getattr(deal.lead, 'public_identifier', '')}: {exc}"
                    )
                    continue

                if result.changed:
                    accelerated += 1
                    self.stdout.write(
                        f"{result.status.upper()} deal={result.deal_id} public_id={result.public_id}"
                    )
                else:
                    skipped += 1
                    self.stdout.write(
                        f"SKIPPED deal={result.deal_id} public_id={result.public_id} reason={result.reason}"
                    )
        finally:
            session.close()

        verb = "would accelerate" if options["dry_run"] else "accelerated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Reply processing complete: {verb} {accelerated}, skipped {skipped}, failed {failed}."
            )
        )
