# Generated manually for LinkedIn → Instagram conversion

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0008_deal_connection_assessment"),
    ]

    operations = [
        migrations.RenameField(
            model_name="lead",
            old_name="linkedin_url",
            new_name="instagram_url",
        ),
        migrations.RenameField(
            model_name="historicallead",
            old_name="linkedin_url",
            new_name="instagram_url",
        ),
        migrations.AlterField(
            model_name="deal",
            name="connection_assessment_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How we last assessed follow-back / DM availability (e.g. api_follows_viewer, ui_message_button).",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="deal",
            name="connection_assessment_confidence",
            field=models.FloatField(
                blank=True,
                help_text="0–1 confidence for the last follow-back / messaging assessment.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicaldeal",
            name="connection_assessment_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How we last assessed follow-back / DM availability (e.g. api_follows_viewer, ui_message_button).",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="historicaldeal",
            name="connection_assessment_confidence",
            field=models.FloatField(
                blank=True,
                help_text="0–1 confidence for the last follow-back / messaging assessment.",
                null=True,
            ),
        ),
    ]
