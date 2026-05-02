# Generated manually for outreach export gates

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0007_lead_sheet_exported_at"),
        ("linkedin", "0012_siteconfig_safe_mode_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemRawLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("level", models.CharField(choices=[("debug", "Debug"), ("info", "Info"), ("warning", "Warning"), ("error", "Error")], default="info", max_length=10)),
                ("category", models.CharField(db_index=True, max_length=64)),
                ("message", models.TextField()),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="linkedin.campaign",
                    ),
                ),
                (
                    "lead",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="crm.lead",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="linkedin.task",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["category", "created_at"], name="lnk_sysrawlog_cat_created"),
                ],
            },
        ),
        migrations.CreateModel(
            name="OutreachEvent",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("invite_sent", "Invite Sent"),
                            ("invite_failed", "Invite Failed"),
                            ("connection_detected", "Connection Detected"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("public_identifier", models.CharField(blank=True, db_index=True, default="", max_length=200)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="outreach_events",
                        to="linkedin.campaign",
                    ),
                ),
                (
                    "deal",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="outreach_events",
                        to="crm.deal",
                    ),
                ),
                (
                    "lead",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.CASCADE,
                        related_name="outreach_events",
                        to="crm.lead",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["lead", "event_type", "created_at"],
                        name="lnk_outreach_lead_evt_cr",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="sheet_export_min_confidence_api",
            field=models.FloatField(
                default=0.85,
                help_text="Minimum connection-detection confidence to export when verified via LinkedIn API 1st degree (no invite required).",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="sheet_export_min_confidence_after_invite",
            field=models.FloatField(
                default=0.55,
                help_text="Minimum confidence for export after an invite_sent event (UI/Message heuristic or API re-check).",
            ),
        ),
    ]
