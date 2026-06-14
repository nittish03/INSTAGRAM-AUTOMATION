from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Regenerate existing unapproved message drafts without approving or sending them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ids",
            default="",
            help="Comma-separated ChatMessage draft ids to regenerate. Defaults to all matching drafts.",
        )
        parser.add_argument(
            "--campaign-id",
            type=int,
            default=None,
            help="Only regenerate drafts for this campaign id.",
        )
        parser.add_argument(
            "--handle",
            default=None,
            help="Django username for the LinkedIn account to use. Defaults to first active profile.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of drafts to process.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Generate replacement text and print what would change, but do not save it.",
        )

    def handle(self, *args, **options):
        from chat.models import ChatMessage
        from crm.models import Lead
        from django.contrib.contenttypes.models import ContentType
        from linkedin.browser.registry import get_or_create_session, resolve_profile
        from linkedin.llm import validate_llm_site_config
        from linkedin.models import SiteConfig
        from linkedin.services.draft_regeneration import regenerate_draft

        linkedin_profile = resolve_profile(options["handle"])
        if linkedin_profile is None:
            raise CommandError("No active LinkedInProfile found.")

        ok, reason = validate_llm_site_config(SiteConfig.load(linkedin_profile.user))
        if not ok:
            raise CommandError(f"LLM configuration invalid: {reason}")

        lead_ct = ContentType.objects.get_for_model(Lead)
        qs = (
            ChatMessage.objects.filter(
                content_type=lead_ct,
                is_draft=True,
                is_approved=False,
                owner=linkedin_profile.user,
                linkedin_profile=linkedin_profile,
            )
            .select_related("campaign", "owner", "linkedin_profile")
            .order_by("id")
        )

        ids = self._parse_ids(options["ids"])
        if ids:
            qs = qs.filter(pk__in=ids)
        if options["campaign_id"]:
            qs = qs.filter(campaign_id=options["campaign_id"])
        if options["limit"] is not None:
            if options["limit"] < 1:
                raise CommandError("--limit must be positive")
            qs = qs[: options["limit"]]

        drafts = list(qs)
        if not drafts:
            self.stdout.write("No matching unapproved drafts found.")
            return

        session = get_or_create_session(linkedin_profile)
        updated = skipped = failed = 0

        try:
            for draft in drafts:
                try:
                    result = regenerate_draft(draft, session, dry_run=options["dry_run"])
                except Exception as exc:
                    failed += 1
                    logger.exception("Failed to regenerate draft %s", draft.pk)
                    self.stderr.write(f"FAILED draft={draft.pk}: {exc}")
                    continue

                if result.status in {"updated", "dry_run"}:
                    updated += 1
                    self.stdout.write(
                        f"{result.status.upper()} draft={result.draft_id} "
                        f"lead={result.public_id} changed={result.changed}"
                    )
                else:
                    skipped += 1
                    self.stdout.write(
                        f"SKIPPED draft={result.draft_id} lead={result.public_id} "
                        f"agent_action={result.status} reason={result.reason}"
                    )
        finally:
            session.close()

        action = "would update" if options["dry_run"] else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Regeneration complete: {action} {updated}, skipped {skipped}, failed {failed}."
            )
        )

    def _parse_ids(self, raw_ids: str) -> list[int]:
        raw_ids = (raw_ids or "").strip()
        if not raw_ids:
            return []
        try:
            return [int(part.strip()) for part in raw_ids.split(",") if part.strip()]
        except ValueError as exc:
            raise CommandError("--ids must be a comma-separated list of integers") from exc
