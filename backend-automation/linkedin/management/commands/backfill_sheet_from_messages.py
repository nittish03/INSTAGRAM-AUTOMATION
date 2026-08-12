"""Backfill Google Sheet rows for already-worked pipeline leads.

DM-first: most prospects sit in QUALIFIED with drafts (or sent FOLLOW_UP), not
CONNECTED. Uses the same sheet_sync helpers as production — no parallel Sheets API.
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef, Q

from chat.models import ChatMessage
from crm.models import Deal, Lead
from google_integration.sheet_sync import (
    sync_messaged_lead_to_google_sheet,
    sync_qualified_lead_to_google_sheet,
)
from linkedin.enums import ProfileState
from linkedin.models import ActionLog, Task


class Command(BaseCommand):
    help = (
        "Upsert sheet rows for worked ICP leads: messaged QUALIFIED/CONNECTED "
        "(successful FOLLOW_UP ActionLog) and/or QUALIFIED leads with drafts. "
        "Skips Failed/disqualified junk by default."
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
        parser.add_argument(
            "--user",
            default="",
            help="Username for SiteConfig / OAuth (default: sole staff user or nittish).",
        )
        parser.add_argument(
            "--messaged-only",
            action="store_true",
            help="Only sync leads with a successful FOLLOW_UP ActionLog.",
        )
        parser.add_argument(
            "--qualified-only",
            action="store_true",
            help="Only sync QUALIFIED leads (drafts / worked pipeline), skip messaged path.",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Also attempt Failed deals (off by default).",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        include_exported = bool(options["include_exported"])
        messaged_only = bool(options["messaged_only"])
        qualified_only = bool(options["qualified_only"])
        include_failed = bool(options["include_failed"])
        if messaged_only and qualified_only:
            raise CommandError("Use only one of --messaged-only or --qualified-only.")

        config_user = self._resolve_user(options.get("user") or "")
        self.stdout.write(f"Using config/OAuth user: {config_user.username} (id={config_user.pk})")

        follow_up_exists = ActionLog.objects.filter(
            target_public_id=OuterRef("public_identifier"),
            action_type=ActionLog.ActionType.FOLLOW_UP,
            status=ActionLog.Status.SUCCESS,
        )
        pipeline_deal = Deal.objects.filter(
            lead_id=OuterRef("pk"),
            state__in=[ProfileState.QUALIFIED, ProfileState.CONNECTED],
        )
        qualified_deal = Deal.objects.filter(
            lead_id=OuterRef("pk"),
            state=ProfileState.QUALIFIED,
        )
        lead_ct = ContentType.objects.get_for_model(Lead)
        draft_exists = ChatMessage.objects.filter(
            content_type=lead_ct,
            object_id=OuterRef("pk"),
            is_outgoing=True,
            is_draft=True,
        )
        follow_up_task_exists = Task.objects.filter(
            deal__lead_id=OuterRef("pk"),
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.COMPLETED,
        )

        messaged_qs = (
            Lead.objects.annotate(
                has_follow_up=Exists(follow_up_exists),
                has_pipeline=Exists(pipeline_deal),
            )
            .filter(has_follow_up=True, has_pipeline=True)
            .exclude(instagram_url="")
            .exclude(public_identifier="")
            .filter(disqualified=False)
            .order_by("pk")
        )
        qualified_qs = (
            Lead.objects.annotate(
                has_qualified=Exists(qualified_deal),
                has_draft=Exists(draft_exists),
                has_follow_up_task=Exists(follow_up_task_exists),
            )
            .filter(has_qualified=True)
            .filter(Q(has_draft=True) | Q(has_follow_up_task=True))
            .exclude(instagram_url="")
            .exclude(public_identifier="")
            .filter(disqualified=False)
            .order_by("pk")
        )

        if not include_exported:
            messaged_qs = messaged_qs.filter(sheet_exported_at__isnull=True)
            qualified_qs = qualified_qs.filter(sheet_exported_at__isnull=True)

        if include_failed:
            # Explicit opt-in: Failed deals are normally junk (blog/web/etc.).
            failed_deal = Deal.objects.filter(lead_id=OuterRef("pk"), state=ProfileState.FAILED)
            failed_qs = (
                Lead.objects.annotate(has_failed=Exists(failed_deal))
                .filter(has_failed=True)
                .exclude(instagram_url="")
                .order_by("pk")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"--include-failed: {failed_qs.count()} Failed lead(s) listed but not auto-exported "
                    "(no production Failed→sheet helper)."
                )
            )

        exported = 0
        skipped = 0
        skip_reasons: dict[str, int] = {}
        seen: set[int] = set()

        def _bump_skip(reason: str) -> None:
            nonlocal skipped
            skipped += 1
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        if not qualified_only:
            self.stdout.write(f"Messaged candidates: {messaged_qs.count()}")
            for lead in messaged_qs.iterator(chunk_size=200):
                seen.add(lead.pk)
                if dry_run:
                    self.stdout.write(
                        f"Would sync (messaged): {lead.public_identifier} (pk={lead.pk})"
                    )
                    exported += 1
                    continue
                if sync_messaged_lead_to_google_sheet(
                    lead, reason_code="backfill_message", config_user=config_user
                ):
                    exported += 1
                    self.stdout.write(f"Exported (messaged): @{lead.public_identifier}")
                else:
                    _bump_skip("messaged_sync_false")

        if not messaged_only:
            # Avoid double-writing leads already handled by messaged path.
            qualified_qs = qualified_qs.exclude(pk__in=seen)
            self.stdout.write(f"Qualified (draft/worked) candidates: {qualified_qs.count()}")
            for lead in qualified_qs.iterator(chunk_size=200):
                if dry_run:
                    self.stdout.write(
                        f"Would sync (qualified): {lead.public_identifier} (pk={lead.pk})"
                    )
                    exported += 1
                    continue
                if sync_qualified_lead_to_google_sheet(
                    lead, reason_code="backfill_qualified", config_user=config_user
                ):
                    exported += 1
                    self.stdout.write(f"Exported (qualified): @{lead.public_identifier}")
                else:
                    _bump_skip("qualified_sync_false")

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: {exported} candidate lead(s) would be synced.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Backfill complete: exported={exported} skipped={skipped}")
            )
            if skip_reasons:
                self.stdout.write(f"Skip reasons: {skip_reasons}")

    def _resolve_user(self, username: str):
        User = get_user_model()
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise CommandError(f"User {username!r} not found") from exc
        # Prefer nittish when present (this deployment's operator).
        nittish = User.objects.filter(username="nittish").first()
        if nittish:
            return nittish
        staff = list(User.objects.filter(is_staff=True).order_by("id")[:2])
        if len(staff) == 1:
            return staff[0]
        raise CommandError("Pass --user <username> (multiple/no staff users).")
