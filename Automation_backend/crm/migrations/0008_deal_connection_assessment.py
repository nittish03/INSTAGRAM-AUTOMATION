# Generated manually — Deal connection inference fields (+ historical)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0007_lead_sheet_exported_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="deal",
            name="connection_assessment_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How we last assessed connection (e.g. api_degree_1, ui_message_button).",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="deal",
            name="connection_assessment_confidence",
            field=models.FloatField(blank=True, help_text="0–1 confidence for the last connection assessment.", null=True),
        ),
        migrations.AddField(
            model_name="deal",
            name="connection_assessed_at",
            field=models.DateTimeField(blank=True, help_text="When connection_assessment_* was last updated.", null=True),
        ),
        migrations.AddField(
            model_name="historicaldeal",
            name="connection_assessment_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How we last assessed connection (e.g. api_degree_1, ui_message_button).",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="historicaldeal",
            name="connection_assessment_confidence",
            field=models.FloatField(blank=True, help_text="0–1 confidence for the last connection assessment.", null=True),
        ),
        migrations.AddField(
            model_name="historicaldeal",
            name="connection_assessed_at",
            field=models.DateTimeField(blank=True, help_text="When connection_assessment_* was last updated.", null=True),
        ),
    ]
