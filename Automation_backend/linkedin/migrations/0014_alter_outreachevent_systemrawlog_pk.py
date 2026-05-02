# Align PK type with Django 6 default (BigAutoField). 0013 used AutoField manually.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("linkedin", "0013_outreach_export_gates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="outreachevent",
            name="id",
            field=models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name="ID",
            ),
        ),
        migrations.AlterField(
            model_name="systemrawlog",
            name="id",
            field=models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name="ID",
            ),
        ),
    ]
