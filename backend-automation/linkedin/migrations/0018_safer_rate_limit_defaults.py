from __future__ import annotations

from django.db import migrations, models


def clamp_existing_profile_limits(apps, schema_editor):
    LinkedInProfile = apps.get_model("linkedin", "LinkedInProfile")
    for profile in LinkedInProfile.objects.all():
        updates = {}
        if profile.connect_daily_limit > 3:
            updates["connect_daily_limit"] = 3
        if profile.connect_weekly_limit > 12:
            updates["connect_weekly_limit"] = 12
        if profile.follow_up_daily_limit > 8:
            updates["follow_up_daily_limit"] = 8
        if updates:
            for field, value in updates.items():
                setattr(profile, field, value)
            profile.save(update_fields=list(updates))


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0017_linkedinprofile_per_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="linkedinprofile",
            name="connect_daily_limit",
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AlterField(
            model_name="linkedinprofile",
            name="connect_weekly_limit",
            field=models.PositiveIntegerField(default=12),
        ),
        migrations.AlterField(
            model_name="linkedinprofile",
            name="follow_up_daily_limit",
            field=models.PositiveIntegerField(default=8),
        ),
        migrations.RunPython(clamp_existing_profile_limits, migrations.RunPython.noop),
    ]
