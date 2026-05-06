import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Max
from django.utils import timezone

from chat.models import ChatMessage
from crm.models import Deal, Lead
from linkedin.models import ActionLog, Campaign, LinkedInProfile, OutreachEvent, SearchKeyword, SiteConfig, Task


class Command(BaseCommand):
    help = "Read-only outreach inspection for Zero. Prints redacted JSON by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pretty",
            action="store_true",
            help="Pretty-print JSON output.",
        )
        parser.add_argument(
            "--include-pii",
            action="store_true",
            help="Include names, public identifiers, emails, and message snippets. Local debugging only.",
        )
        parser.add_argument(
            "--include-internal-ids",
            action="store_true",
            help="Include raw database row IDs. Local debugging only.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        self.include_pii = bool(options["include_pii"])
        self.include_internal_ids = bool(options["include_internal_ids"])
        data = {
            "generated_at_utc": now.isoformat(),
            "repo": "Automation_backend",
            "counts": self._counts(),
            "campaigns": self._campaigns(),
            "site_config": self._site_config(),
            "linkedin_profiles": self._profiles(),
            "deals": self._deals(),
            "tasks": self._tasks(now),
            "outreach_events": self._outreach_events(),
            "actions": self._actions(),
            "messages": self._messages(now),
            "export_ready": self._export_ready(),
        }
        indent = 2 if options["pretty"] else None
        self.stdout.write(json.dumps(data, default=str, indent=indent))

    def _counts(self):
        return {
            "campaigns": Campaign.objects.count(),
            "leads": Lead.objects.count(),
            "deals": Deal.objects.count(),
            "tasks": Task.objects.count(),
            "outreach_events": OutreachEvent.objects.count(),
            "action_logs": ActionLog.objects.count(),
            "messages": ChatMessage.objects.count(),
            "linkedin_profiles": LinkedInProfile.objects.count(),
            "search_keywords": SearchKeyword.objects.count(),
        }

    def _campaigns(self):
        rows = []
        for campaign in Campaign.objects.all().order_by("id"):
            row = {
                "name": campaign.name,
                "is_freemium": campaign.is_freemium,
                "action_fraction": campaign.action_fraction,
                "deals": Deal.objects.filter(campaign=campaign).count(),
                "messages": ChatMessage.objects.filter(campaign=campaign).count(),
                "actions": ActionLog.objects.filter(campaign=campaign).count(),
                "events": OutreachEvent.objects.filter(campaign=campaign).count(),
                "last_action": ActionLog.objects.filter(campaign=campaign).aggregate(value=Max("created_at"))["value"],
            }
            if self.include_internal_ids:
                row["id"] = campaign.id
            rows.append(row)
        return rows

    def _site_config(self):
        rows = []
        for row in SiteConfig.objects.values(
            "id",
            "google_sheet_sync_enabled",
            "google_sheet_tab",
            "safe_mode_enabled",
            "global_pause_outreach",
            "pause_new_connection_invites",
            "max_bulk_approve",
            "max_bulk_export",
            "sheet_export_min_confidence_api",
            "sheet_export_min_confidence_after_invite",
        ):
            if not self.include_internal_ids:
                row.pop("id", None)
            rows.append(row)
        return rows

    def _profiles(self):
        rows = []
        for row in LinkedInProfile.objects.values(
            "id",
            "user__username",
            "linkedin_username",
            "active",
            "connect_daily_limit",
            "connect_weekly_limit",
            "follow_up_daily_limit",
            "legal_accepted",
            "newsletter_processed",
        ):
            if not self.include_internal_ids:
                row.pop("id", None)
            if not self.include_pii:
                row.pop("user__username", None)
                row.pop("linkedin_username", None)
            rows.append(row)
        return rows

    def _deals(self):
        return {
            "by_state": list(Deal.objects.values("state").annotate(count=Count("id")).order_by("-count")),
            "by_closing_reason": list(
                Deal.objects.exclude(closing_reason="")
                .values("closing_reason")
                .annotate(count=Count("id"))
                .order_by("-count")
            ),
        }

    def _tasks(self, now):
        data = {
            "by_status": list(Task.objects.values("status").annotate(count=Count("id")).order_by("-count")),
            "by_type_status": list(
                Task.objects.values("task_type", "status")
                .annotate(count=Count("id"))
                .order_by("task_type", "status")
            ),
            "pending_due_now": Task.objects.filter(status=Task.Status.PENDING, scheduled_at__lte=now).count(),
            "pending_overdue_24h": Task.objects.filter(
                status=Task.Status.PENDING,
                scheduled_at__lte=now - timedelta(hours=24),
            ).count(),
            "running_over_1h": Task.objects.filter(
                status=Task.Status.RUNNING,
                started_at__lte=now - timedelta(hours=1),
            ).count(),
            "failed_last_7d": Task.objects.filter(
                status=Task.Status.FAILED,
                ended_at__gte=now - timedelta(days=7),
            ).count(),
            "pending_sample": list(
                Task.objects.filter(status=Task.Status.PENDING)
                .order_by("scheduled_at")
                .values("id", "task_type", "scheduled_at", "deal_id")[:10]
            ),
            "recent_failed_sample": [self._task_error(row) for row in Task.objects.filter(status=Task.Status.FAILED).order_by("-ended_at")[:5]],
        }
        if not self.include_internal_ids:
            for row in data["pending_sample"]:
                row.pop("id", None)
                row.pop("deal_id", None)
        return data

    def _task_error(self, task):
        error = task.error or ""
        first_line = next((line.strip() for line in error.splitlines() if line.strip()), "")
        exception_line = next((line.strip() for line in reversed(error.splitlines()) if line.strip()), first_line)
        row = {
            "task_type": task.task_type,
            "ended_at": task.ended_at,
            "error_summary": self._redact_text(exception_line or first_line, limit=220),
        }
        if self.include_internal_ids:
            row["id"] = task.id
        return row

    def _outreach_events(self):
        return list(
            OutreachEvent.objects.values("event_type")
            .annotate(count=Count("id"), last=Max("created_at"))
            .order_by("-count")
        )

    def _actions(self):
        return {
            "by_type_status": list(
                ActionLog.objects.values("action_type", "status")
                .annotate(count=Count("id"), last=Max("created_at"))
                .order_by("action_type", "status")
            ),
            "latest": [self._action_row(row) for row in ActionLog.objects.order_by("-created_at")[:8]],
        }

    def _action_row(self, action):
        row = {
            "action_type": action.action_type,
            "status": action.status,
            "created_at": action.created_at,
        }
        if self.include_internal_ids:
            row["id"] = action.id
        if self.include_pii:
            row["target_name"] = action.target_name
            row["target_public_id"] = action.target_public_id
        return row

    def _messages(self, now):
        latest = []
        for message in ChatMessage.objects.order_by("-creation_date")[:8]:
            row = {
                "is_outgoing": message.is_outgoing,
                "is_draft": message.is_draft,
                "is_approved": message.is_approved,
                "creation_date": message.creation_date,
            }
            if self.include_internal_ids:
                row["id"] = message.id
                row["campaign_id"] = message.campaign_id
                row["object_id"] = message.object_id
            if self.include_pii:
                row["content_snippet"] = self._redact_text(message.content or "", limit=160)
            latest.append(row)
        return {
            "incoming": ChatMessage.objects.filter(is_outgoing=False).count(),
            "outgoing": ChatMessage.objects.filter(is_outgoing=True).count(),
            "drafts": ChatMessage.objects.filter(is_draft=True).count(),
            "approved": ChatMessage.objects.filter(is_approved=True).count(),
            "incoming_last_7d": ChatMessage.objects.filter(is_outgoing=False, creation_date__gte=now - timedelta(days=7)).count(),
            "outgoing_last_7d": ChatMessage.objects.filter(is_outgoing=True, creation_date__gte=now - timedelta(days=7)).count(),
            "latest": latest,
        }

    def _export_ready(self):
        from linkedin.enums import ProfileState

        verified = 0
        awaiting_verification = 0
        samples = []
        deals = Deal.objects.filter(
            state=ProfileState.CONNECTED.value,
            lead__sheet_exported_at__isnull=True,
        ).select_related("lead")
        for deal in deals.iterator(chunk_size=300):
            if not deal.lead:
                continue
            ok, reason, label = self._lead_sheet_export_verification_read_only(deal.lead)
            if ok:
                verified += 1
                if len(samples) < 8:
                    row = {"reason": reason, "label": label}
                    if self.include_internal_ids:
                        row["lead_id"] = deal.lead_id
                    if self.include_pii:
                        row["public_identifier"] = deal.lead.public_identifier
                    samples.append(row)
            else:
                awaiting_verification += 1
        return {
            "connected_unexported_verified": verified,
            "connected_unexported_awaiting_verification": awaiting_verification,
            "sample": samples,
        }

    def _lead_sheet_export_verification_read_only(self, lead):
        from linkedin.enums import ProfileState

        if not lead.deal_set.filter(state=ProfileState.CONNECTED).exists():
            return False, "not_connected", ""

        cfg = SiteConfig.objects.first()
        min_api = float(cfg.sheet_export_min_confidence_api) if cfg else 0.85
        min_after = float(cfg.sheet_export_min_confidence_after_invite) if cfg else 0.55

        detects = list(
            OutreachEvent.objects.filter(
                lead=lead,
                event_type=OutreachEvent.EventType.CONNECTION_DETECTED,
            ).order_by("created_at")
        )
        if not detects:
            return False, "no_connection_detected_event", ""

        latest = detects[-1]
        meta = latest.metadata or {}
        src = (meta.get("source") or "").strip()
        conf = float(meta.get("confidence") or 0.0)

        if src == "api_degree_1" and conf >= min_api:
            return True, "verified_api_first_degree", "Verified (API)"

        invites = list(
            OutreachEvent.objects.filter(
                lead=lead,
                event_type=OutreachEvent.EventType.INVITE_SENT,
            ).order_by("created_at")
        )
        if not invites:
            return False, "no_invite_for_non_api_path", ""

        last_invite_at = invites[-1].created_at
        if latest.created_at < last_invite_at:
            return False, "detection_before_last_invite", ""

        if conf >= min_after and src in ("api_degree_1", "ui_message_button"):
            return True, "verified_after_invite", "Accepted (post-invite)"

        return False, "insufficient_confidence_or_source", ""

    def _redact_text(self, value, limit=160):
        text = (value or "").replace("\\n", " ")
        if self.include_pii:
            return text[:limit]
        return "[redacted]" if text else ""
