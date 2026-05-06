from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0015_add_reply_check_task_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfig",
            name="pause_new_connection_invites",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Stops new connection invite expansion while allowing monitoring, replies, "
                    "follow-ups, and existing pending invite checks to continue."
                ),
            ),
        ),
    ]
