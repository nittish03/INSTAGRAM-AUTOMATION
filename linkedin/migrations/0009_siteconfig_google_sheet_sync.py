# Generated manually for Google Sheet lead export settings

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("linkedin", "0008_rename_completed_at_task_ended_at_historicaltask"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfig",
            name="google_sheet_sync_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Append new/enriched leads as rows to the Google Sheet below (uses Google Sheets API).",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="google_sheet_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Spreadsheet ID from the URL: docs.google.com/spreadsheets/d/<THIS_PART>/",
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="google_sheet_tab",
            field=models.CharField(
                blank=True,
                default="Sheet1",
                help_text="Tab name (e.g. Sheet1). Rows append to columns A–G: Name, Company, Position, LinkedIn, Connected, Status, Action.",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="google_sheet_sync_user",
            field=models.ForeignKey(
                blank=True,
                help_text="Whose Google OAuth tokens to use. Leave empty to use the first superuser with Google connected.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
