from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from linkedin.enums import ProfileState
from simple_history.models import HistoricalRecords


class ClosingReason(models.TextChoices):
    COMPLETED = "Completed"
    FAILED = "Failed"
    DISQUALIFIED = "Disqualified"


class Deal(models.Model):
    class Meta:
        verbose_name = _("Deal")
        verbose_name_plural = _("Deals")
        constraints = [
            models.UniqueConstraint(fields=["lead", "campaign"], name="unique_deal_per_campaign"),
        ]

    lead = models.ForeignKey("Lead", on_delete=models.CASCADE)
    campaign = models.ForeignKey(
        "linkedin.Campaign", on_delete=models.CASCADE, related_name="deals",
    )
    state = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in ProfileState],
        default=ProfileState.QUALIFIED,
    )
    closing_reason = models.CharField(
        max_length=20,
        choices=ClosingReason.choices,
        blank=True,
        default="",
    )
    reason = models.TextField(blank=True, default="")
    connect_attempts = models.IntegerField(default=0)
    backoff_hours = models.IntegerField(default=0)
    creation_date = models.DateTimeField(default=timezone.now)
    update_date = models.DateTimeField(auto_now=True)

    # Latest connection *inference* (API/UI heuristic). Export uses OutreachEvent + confidence, not this alone.
    connection_assessment_source = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="How we last assessed connection (e.g. api_degree_1, ui_message_button).",
    )
    connection_assessment_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="0–1 confidence for the last connection assessment.",
    )
    connection_assessed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When connection_assessment_* was last updated.",
    )

    history = HistoricalRecords()

    def __str__(self):
        lead_str = str(self.lead) if self.lead_id else "?"
        return f"{lead_str} [{self.state}]"
