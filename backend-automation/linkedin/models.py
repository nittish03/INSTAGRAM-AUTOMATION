import logging
import base64
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from cryptography.fernet import Fernet, InvalidToken
from simple_history.models import HistoricalRecords

logger = logging.getLogger(__name__)
_decrypt_invalid_token_logged = False

def _get_cipher():
    # [NEW-CRIT-02] Dedicated env var for encryption; dev fallback matches django_settings (non-production).
    from django.core.exceptions import ImproperlyConfigured

    raw_key = os.environ.get("LEADPILOT_ENCRYPTION_KEY", "").encode()
    is_production = os.environ.get("ENV", "").lower() == "production"
    if not raw_key or len(raw_key) < 32:
        if settings.DEBUG or not is_production:
            import hashlib

            key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(key))
        raise ImproperlyConfigured(
            "LEADPILOT_ENCRYPTION_KEY must be set (UTF-8 string at least 32 bytes) when ENV=production."
        )
    
    key = base64.urlsafe_b64encode(raw_key[:32])
    return Fernet(key)

def encrypt_value(value: str) -> str:
    if not value: return ""
    cipher = _get_cipher()
    return cipher.encrypt(value.encode()).decode()

def decrypt_value(value: str) -> str:
    if not value: return ""
    try:
        cipher = _get_cipher()
        return cipher.decrypt(value.encode()).decode()
    except InvalidToken:
        global _decrypt_invalid_token_logged
        if not _decrypt_invalid_token_logged:
            _decrypt_invalid_token_logged = True
            logger.debug(
                "decrypt_value received legacy/plaintext or key-mismatched data; "
                "returning raw value and suppressing repeat InvalidToken logs"
            )
        return value
    except Exception as exc:
        logger.warning(
            "decrypt_value failed (%s); returning raw value for compatibility",
            exc.__class__.__name__,
        )
        return value # Fallback for old plaintext data during transition


# action_type → (daily_limit_field, weekly_limit_field)
_RATE_LIMIT_FIELDS = {
    "connect": ("connect_daily_limit", "connect_weekly_limit"),
    "follow_up": ("follow_up_daily_limit", None),
}


class SiteConfig(models.Model):
    """Singleton model for global site configuration (LLM keys, etc.)."""

    LLM_PROVIDER_CHOICES = (
        ("openai", "OpenAI Compatible"),
        ("azure", "Azure OpenAI / Foundry"),
        ("gemini", "Google Gemini"),
    )

    llm_api_key = models.CharField(max_length=500, blank=True, default="")
    llm_provider = models.CharField(
        max_length=20,
        choices=LLM_PROVIDER_CHOICES,
        default="openai",
    )
    ai_model = models.CharField(max_length=200, blank=True, default="")
    llm_api_base = models.CharField(max_length=500, blank=True, default="")
    azure_deployment = models.CharField(max_length=200, blank=True, default="")
    azure_api_version = models.CharField(max_length=50, blank=True, default="2024-10-21")

    google_sheet_sync_enabled = models.BooleanField(
        default=False,
        help_text="Append new/enriched leads as rows to the Google Sheet below (uses Google Sheets API).",
    )
    google_sheet_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Paste the full Google Sheets browser URL or the bare spreadsheet id (saved as id only).",
    )
    google_sheet_tab = models.CharField(
        max_length=100,
        blank=True,
        default="Sheet1",
        help_text="Tab name (e.g. Sheet1). Rows append to columns A–G: Name, Company, Position, LinkedIn, Connected, Status, Action.",
    )
    google_sheet_sync_user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Whose Google OAuth tokens to use. Leave empty to use the first superuser with Google connected.",
    )
    safe_mode_enabled = models.BooleanField(
        default=True,
        help_text="If enabled, bulk and risky operator actions are guarded by stricter limits.",
    )
    global_pause_outreach = models.BooleanField(
        default=False,
        help_text="Hard pause for queueing new outreach actions from operator workflows.",
    )
    pause_new_connection_invites = models.BooleanField(
        default=False,
        help_text=(
            "Stops new connection invite expansion while allowing monitoring, replies, "
            "follow-ups, and existing pending invite checks to continue."
        ),
    )
    max_bulk_approve = models.PositiveIntegerField(
        default=25,
        help_text="Maximum draft approvals allowed per bulk operator action.",
    )
    max_bulk_export = models.PositiveIntegerField(
        default=50,
        help_text="Maximum lead exports allowed per bulk operator action.",
    )
    sheet_export_min_confidence_api = models.FloatField(
        default=0.85,
        help_text="Minimum connection-detection confidence to export when verified via LinkedIn API 1st degree (no invite required).",
    )
    sheet_export_min_confidence_after_invite = models.FloatField(
        default=0.55,
        help_text="Minimum confidence for export after an invite_sent event (UI/Message heuristic or API re-check).",
    )

    class Meta:
        app_label = "linkedin"
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

    def __str__(self):
        return "Site Configuration"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.llm_api_key and self.llm_api_key.startswith('gAAAA'):
            self.llm_api_key = decrypt_value(self.llm_api_key)

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        if self.llm_api_key and self.llm_api_key.startswith('gAAAA'):
            self.llm_api_key = decrypt_value(self.llm_api_key)

    def save(self, *args, **kwargs):
        from google_integration.spreadsheet_id import normalize_spreadsheet_id

        self.google_sheet_id = normalize_spreadsheet_id(self.google_sheet_id)
        plain_key = self.llm_api_key
        if self.llm_api_key and not self.llm_api_key.startswith('gAAAA'):
            self.llm_api_key = encrypt_value(self.llm_api_key)
        self.pk = 1
        super().save(*args, **kwargs)
        self.llm_api_key = plain_key

    @classmethod
    def load(cls) -> "SiteConfig":

        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Campaign(models.Model):
    name = models.CharField(max_length=200, unique=True)
    users = models.ManyToManyField(User, blank=True, related_name="campaigns")
    product_docs = models.TextField(blank=True)
    campaign_objective = models.TextField(blank=True)
    booking_link = models.URLField(max_length=500, blank=True)
    is_freemium = models.BooleanField(
        default=False, 
        help_text="Uses a pre-trained kit model instead of active learning. Optimized for standard hiring/sales personas."
    )

    action_fraction = models.FloatField(default=0.2)
    seed_public_ids = models.JSONField(default=list, blank=True)

    def _get_model_path(self):
        return settings.BASE_DIR / "models" / f"campaign_{self.pk}.joblib"

    def save_ml_model(self, pipeline):
        import joblib
        path = self._get_model_path()
        path.parent.mkdir(exist_ok=True)
        joblib.dump(pipeline, path)
        # Touch update_date or similar if needed, or just log
        logger.debug("Saved ML model to %s", path)

    def load_ml_model(self):
        import joblib
        path = self._get_model_path()
        if path.exists():
            try:
                return joblib.load(path)
            except Exception:
                logger.warning("Failed to load ML model from %s", path)
        
        if self.is_freemium:
            kit_path = settings.BASE_DIR / "models" / "kit.joblib"
            if kit_path.exists():
                try:
                    return joblib.load(kit_path)
                except Exception:
                    logger.warning("Failed to load kit ML model from %s", kit_path)
        return None

    def __str__(self):
        return self.name

    class Meta:
        app_label = "linkedin"


class LinkedInProfile(models.Model):
    # Multi-tenant ownership: each Django admin/superadmin owns the LinkedIn
    # accounts they've personally connected. They can only see and manage their
    # own profiles. Listing, toggling and deletion are scoped to ``user`` on the
    # API layer (see ``linkedin.views.api_linkedin_profiles``).
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="linkedin_profiles",
    )
    self_lead = models.ForeignKey(
        "crm.Lead",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    linkedin_username = models.CharField(max_length=200)
    linkedin_password = models.CharField(max_length=200)
    subscribe_newsletter = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    connect_daily_limit = models.PositiveIntegerField(default=20)
    connect_weekly_limit = models.PositiveIntegerField(default=100)
    follow_up_daily_limit = models.PositiveIntegerField(default=30)
    legal_accepted = models.BooleanField(default=False)
    cookie_data = models.JSONField(null=True, blank=True)
    newsletter_processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._exhausted: dict[str, date] = {}
        if self.linkedin_password and self.linkedin_password.startswith('gAAAA'):
            self.linkedin_password = decrypt_value(self.linkedin_password)

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        if self.linkedin_password and self.linkedin_password.startswith('gAAAA'):
            self.linkedin_password = decrypt_value(self.linkedin_password)

    def save(self, *args, **kwargs):
        plain_password = self.linkedin_password
        if self.linkedin_password and not self.linkedin_password.startswith('gAAAA'):
            self.linkedin_password = encrypt_value(self.linkedin_password)
        super().save(*args, **kwargs)
        self.linkedin_password = plain_password

    def can_execute(self, action_type: str) -> bool:
        """Check if the action is allowed under daily/weekly rate limits."""
        # Reset exhaustion flag on a new day
        exhausted_date = self._exhausted.get(action_type)
        if exhausted_date is not None and exhausted_date != date.today():
            del self._exhausted[action_type]
        if action_type in self._exhausted:
            return False

        daily_field, weekly_field = _RATE_LIMIT_FIELDS[action_type]

        self.refresh_from_db(fields=[daily_field] + ([weekly_field] if weekly_field else []))

        daily_limit = getattr(self, daily_field)
        if daily_limit is not None and self._daily_count(action_type) >= daily_limit:
            return False

        if weekly_field:
            weekly_limit = getattr(self, weekly_field)
            if weekly_limit is not None and self._weekly_count(action_type) >= weekly_limit:
                return False

        return True

    def record_action(
        self, action_type: str, campaign: Campaign,
        target_name: str = "", target_public_id: str = "",
        status: str = "success", note: str = ""
    ) -> None:
        """Persist a rate-limited action with detailed prospect metrics."""
        ActionLog.objects.create(
            linkedin_profile=self,
            campaign=campaign,
            action_type=action_type,
            target_name=target_name,
            target_public_id=target_public_id,
            status=status,
            note=note
        )

    def mark_exhausted(self, action_type: str) -> None:
        """Mark the action type as externally exhausted for today."""
        self._exhausted[action_type] = date.today()
        logger.warning("Rate limit: %s externally exhausted for today", action_type)

    def _daily_count(self, action_type: str) -> int:
        now_local = timezone.localtime(timezone.now())
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        return ActionLog.objects.filter(
            linkedin_profile=self, action_type=action_type,
            created_at__gte=today_start,
        ).count()

    def _weekly_count(self, action_type: str) -> int:
        now_local = timezone.localtime(timezone.now())
        monday = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        return ActionLog.objects.filter(
            linkedin_profile=self, action_type=action_type,
            created_at__gte=monday,
        ).count()

    def __repr__(self):
        return f"{self.user.username} ({self.linkedin_username})"

    def __str__(self):
        return f"{self.user.username} ({self.linkedin_username})"


    class Meta:
        app_label = "linkedin"
        # Same Django user can't add the same LinkedIn handle twice. Different
        # users can independently connect the same LinkedIn handle (rare but
        # legal — e.g. a shared corporate account).
        constraints = [
            models.UniqueConstraint(
                fields=["user", "linkedin_username"],
                name="uniq_linkedinprofile_user_username",
            ),
        ]


class SearchKeyword(models.Model):
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="search_keywords",
    )
    keyword = models.CharField(max_length=500)
    used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "linkedin"
        unique_together = [("campaign", "keyword")]

    def __str__(self):
        return self.keyword


class ActionLog(models.Model):
    class ActionType(models.TextChoices):
        CONNECT = "connect", "Connect"
        FOLLOW_UP = "follow_up", "Follow Up"

    class Status(models.TextChoices):
        SUCCESS = "success"
        FAILED = "failed"

    linkedin_profile = models.ForeignKey(
        LinkedInProfile,
        on_delete=models.CASCADE,
        related_name="action_logs",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="action_logs",
    )
    action_type = models.CharField(max_length=20, choices=ActionType.choices)
    target_name = models.CharField(max_length=200, blank=True, default="")
    target_public_id = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUCCESS)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "linkedin"
        indexes = [
            models.Index(fields=["linkedin_profile", "action_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action_type} by {self.linkedin_profile} at {self.created_at}"


class SystemRawLog(models.Model):
    """Debug / internal diagnostics only. Never used for exports, analytics, or reporting."""

    class Level(models.TextChoices):
        DEBUG = "debug"
        INFO = "info"
        WARNING = "warning"
        ERROR = "error"

    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    category = models.CharField(max_length=64, db_index=True)
    message = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    task = models.ForeignKey("linkedin.Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "linkedin"
        indexes = [
            models.Index(fields=["category", "created_at"], name="lnk_sysrawlog_cat_created"),
        ]

    def __str__(self):
        return f"{self.category} [{self.level}] {self.created_at}"


class OutreachEvent(models.Model):
    """Explicit outreach actions and outcomes. Drives export eligibility — not inferred from Deal state alone."""

    class EventType(models.TextChoices):
        INVITE_SENT = "invite_sent"
        INVITE_FAILED = "invite_failed"
        CONNECTION_DETECTED = "connection_detected"

    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.CASCADE, related_name="outreach_events")
    deal = models.ForeignKey("crm.Deal", null=True, blank=True, on_delete=models.SET_NULL, related_name="outreach_events")
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name="outreach_events")
    public_identifier = models.CharField(max_length=200, blank=True, default="", db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "linkedin"
        indexes = [
            models.Index(
                fields=["lead", "event_type", "created_at"],
                name="lnk_outreach_lead_evt_cr",
            ),
        ]

    def __str__(self):
        return f"{self.event_type} {self.public_identifier or self.lead_id} @ {self.created_at}"


class TaskQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status=Task.Status.PENDING).order_by("scheduled_at")

    def due(self):
        return self.pending().filter(scheduled_at__lte=timezone.now())

    def runnable(self):
        qs = self.due()
        if bool(getattr(SiteConfig.load(), "pause_new_connection_invites", False)):
            return qs.exclude(task_type=Task.TaskType.CONNECT)
        return qs

    def claim_next(self) -> "Task | None":
        return self.runnable().first()

    def seconds_to_next(self) -> float | None:
        """Seconds until the next pending task, or None if queue is empty."""
        qs = self.pending()
        if bool(getattr(SiteConfig.load(), "pause_new_connection_invites", False)):
            qs = qs.exclude(task_type=Task.TaskType.CONNECT)
        next_task = qs.only("scheduled_at").first()
        if next_task is None:
            return None
        return max((next_task.scheduled_at - timezone.now()).total_seconds(), 0)


class Task(models.Model):
    class TaskType(models.TextChoices):
        CONNECT = "connect"
        CHECK_PENDING = "check_pending"
        FOLLOW_UP = "follow_up"
        SEND_MESSAGE = "send_message"
        REPLY_CHECK = "reply_check"

    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"

    task_type = models.CharField(max_length=20, choices=TaskType.choices)
    deal = models.ForeignKey(
        "crm.Deal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tasks", help_text="The deal this task targets (allows fast indexing)"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    scheduled_at = models.DateTimeField()
    payload = models.JSONField(default=dict)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    objects = TaskQuerySet.as_manager()

    class Meta:
        app_label = "linkedin"
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        return f"{self.task_type} [{self.status}] scheduled={self.scheduled_at}"

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_completed(self):
        self.status = self.Status.COMPLETED
        self.ended_at = timezone.now()
        self.save(update_fields=["status", "ended_at"])

    def mark_skipped(self, reason: str = ""):
        self.status = self.Status.SKIPPED
        self.error = reason
        self.ended_at = timezone.now()
        self.save(update_fields=["status", "error", "ended_at"])

    def mark_failed(self, error: str):
        self.status = self.Status.FAILED
        self.error = error
        self.ended_at = timezone.now()
        self.save(update_fields=["status", "error", "ended_at"])
