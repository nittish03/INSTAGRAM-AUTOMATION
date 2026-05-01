# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0006_remove_historicallead_embedding_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicallead",
            name="sheet_exported_at",
            field=models.DateTimeField(blank=True, help_text="Set when this lead was appended to the configured Google Sheet (avoids duplicates).", null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="sheet_exported_at",
            field=models.DateTimeField(blank=True, help_text="Set when this lead was appended to the configured Google Sheet (avoids duplicates).", null=True),
        ),
    ]
