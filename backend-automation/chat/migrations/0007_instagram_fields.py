# Generated manually for LinkedIn → Instagram conversion

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0006_chatmessage_linkedin_profile"),
        ("linkedin", "0021_instagram_conversion"),
    ]

    operations = [
        migrations.RenameField(
            model_name="chatmessage",
            old_name="linkedin_profile",
            new_name="instagram_profile",
        ),
        migrations.RenameField(
            model_name="chatmessage",
            old_name="linkedin_urn",
            new_name="instagram_message_id",
        ),
        migrations.AlterField(
            model_name="chatmessage",
            name="instagram_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="linkedin.instagramprofile",
                verbose_name="Instagram Profile",
            ),
        ),
        migrations.AlterField(
            model_name="chatmessage",
            name="instagram_message_id",
            field=models.CharField(
                help_text="Stable Instagram DM id used for dedup (GraphQL item id or synthetic hash)",
                max_length=300,
                unique=True,
                verbose_name="Instagram message id",
            ),
        ),
    ]
