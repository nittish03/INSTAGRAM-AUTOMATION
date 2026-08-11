# LinkedIn → Instagram: rename Deal follow/assessment fields (preserve data).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0009_instagram_fields"),
    ]

    operations = [
        migrations.RenameField(
            model_name="deal",
            old_name="connect_attempts",
            new_name="follow_attempts",
        ),
        migrations.RenameField(
            model_name="historicaldeal",
            old_name="connect_attempts",
            new_name="follow_attempts",
        ),
        migrations.RenameField(
            model_name="deal",
            old_name="connection_assessment_source",
            new_name="follow_assessment_source",
        ),
        migrations.RenameField(
            model_name="historicaldeal",
            old_name="connection_assessment_source",
            new_name="follow_assessment_source",
        ),
        migrations.RenameField(
            model_name="deal",
            old_name="connection_assessment_confidence",
            new_name="follow_assessment_confidence",
        ),
        migrations.RenameField(
            model_name="historicaldeal",
            old_name="connection_assessment_confidence",
            new_name="follow_assessment_confidence",
        ),
        migrations.RenameField(
            model_name="deal",
            old_name="connection_assessed_at",
            new_name="follow_assessed_at",
        ),
        migrations.RenameField(
            model_name="historicaldeal",
            old_name="connection_assessed_at",
            new_name="follow_assessed_at",
        ),
        migrations.AlterField(
            model_name="deal",
            name="follow_assessment_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How we last assessed follow status (e.g. api_follows_viewer, ui_message_button).",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="deal",
            name="follow_assessment_confidence",
            field=models.FloatField(
                blank=True,
                help_text="0–1 confidence for the last follow assessment.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="deal",
            name="follow_assessed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When follow_assessment_* was last updated.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicaldeal",
            name="follow_assessment_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How we last assessed follow status (e.g. api_follows_viewer, ui_message_button).",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="historicaldeal",
            name="follow_assessment_confidence",
            field=models.FloatField(
                blank=True,
                help_text="0–1 confidence for the last follow assessment.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicaldeal",
            name="follow_assessed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When follow_assessment_* was last updated.",
                null=True,
            ),
        ),
    ]
