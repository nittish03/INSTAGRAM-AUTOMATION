from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def backfill_message_profiles(apps, schema_editor):
    ChatMessage = apps.get_model("chat", "ChatMessage")
    LinkedInProfile = apps.get_model("linkedin", "LinkedInProfile")

    profile_by_user: dict[int, int] = {}
    profiles = (
        LinkedInProfile.objects.filter(user_id__isnull=False)
        .order_by("user_id", "-active", "-created_at", "id")
        .values_list("user_id", "id")
    )
    for user_id, profile_id in profiles:
        profile_by_user.setdefault(user_id, profile_id)

    for user_id, profile_id in profile_by_user.items():
        ChatMessage.objects.filter(owner_id=user_id, linkedin_profile_id__isnull=True).update(
            linkedin_profile_id=profile_id,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0019_siteconfig_per_user"),
        ("chat", "0005_chatmessage_campaign"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="linkedin_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="linkedin.linkedinprofile",
                verbose_name="LinkedIn Profile",
            ),
        ),
        migrations.RunPython(backfill_message_profiles, migrations.RunPython.noop),
    ]
