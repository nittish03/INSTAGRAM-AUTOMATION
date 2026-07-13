from __future__ import annotations

from django.db import migrations, models


CONNECT_DAILY_TARGET = 35
CONNECT_WEEKLY_TARGET = 175
FOLLOW_UP_DAILY_TARGET = 25


def raise_existing_profile_limits(apps, schema_editor):
    LinkedInProfile = apps.get_model("linkedin", "LinkedInProfile")
    LinkedInProfile.objects.filter(connect_daily_limit__lt=CONNECT_DAILY_TARGET).update(
        connect_daily_limit=CONNECT_DAILY_TARGET
    )
    LinkedInProfile.objects.filter(connect_weekly_limit__lt=CONNECT_WEEKLY_TARGET).update(
        connect_weekly_limit=CONNECT_WEEKLY_TARGET
    )
    LinkedInProfile.objects.filter(follow_up_daily_limit__lt=FOLLOW_UP_DAILY_TARGET).update(
        follow_up_daily_limit=FOLLOW_UP_DAILY_TARGET
    )


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0019_siteconfig_per_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="linkedinprofile",
            name="connect_daily_limit",
            field=models.PositiveIntegerField(default=CONNECT_DAILY_TARGET),
        ),
        migrations.AlterField(
            model_name="linkedinprofile",
            name="connect_weekly_limit",
            field=models.PositiveIntegerField(default=CONNECT_WEEKLY_TARGET),
        ),
        migrations.AlterField(
            model_name="linkedinprofile",
            name="follow_up_daily_limit",
            field=models.PositiveIntegerField(default=FOLLOW_UP_DAILY_TARGET),
        ),
        migrations.RunPython(raise_existing_profile_limits, migrations.RunPython.noop),
    ]
