from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0011_siteconfig_azure_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfig",
            name="global_pause_outreach",
            field=models.BooleanField(
                default=False,
                help_text="Hard pause for queueing new outreach actions from operator workflows.",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="max_bulk_approve",
            field=models.PositiveIntegerField(
                default=25,
                help_text="Maximum draft approvals allowed per bulk operator action.",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="max_bulk_export",
            field=models.PositiveIntegerField(
                default=50,
                help_text="Maximum lead exports allowed per bulk operator action.",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="safe_mode_enabled",
            field=models.BooleanField(
                default=True,
                help_text="If enabled, bulk and risky operator actions are guarded by stricter limits.",
            ),
        ),
    ]
