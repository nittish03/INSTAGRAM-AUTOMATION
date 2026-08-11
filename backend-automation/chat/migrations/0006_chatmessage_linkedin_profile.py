from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def backfill_message_profiles(apps, schema_editor):
    """Attach each owner's active InstagramProfile to messages missing a profile FK.

    Field is still named ``linkedin_profile`` here so ``0007_instagram_fields`` can
    RenameField → ``instagram_profile`` on all DBs (including ones that applied an
    older LinkedIn-era 0006). Model target is InstagramProfile because this
    migration depends on ``linkedin.0021_instagram_conversion``.
    """
    ChatMessage = apps.get_model("chat", "ChatMessage")
    InstagramProfile = apps.get_model("linkedin", "InstagramProfile")

    profile_by_user: dict[int, int] = {}
    profiles = (
        InstagramProfile.objects.filter(user_id__isnull=False)
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
        # 0021 renames LinkedInProfile → InstagramProfile. This migration must run
        # after that rename so the FK target resolves (user DBs may already have
        # 0021 applied). Do NOT reverse this to depend on 0020 + make 0021 depend
        # on 0006 — that breaks DBs where 0021 is already recorded as applied.
        ("linkedin", "0021_instagram_conversion"),
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
                to="linkedin.instagramprofile",
                verbose_name="Instagram Profile",
            ),
        ),
        migrations.RunPython(backfill_message_profiles, migrations.RunPython.noop),
    ]
