from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def copy_global_config_to_staff_users(apps, schema_editor):
    SiteConfig = apps.get_model("linkedin", "SiteConfig")
    User = apps.get_model("auth", "User")
    global_cfg = SiteConfig.objects.filter(pk=1).first()
    if global_cfg is None:
        global_cfg = SiteConfig.objects.create(pk=1, user=None)

    copy_fields = [
        "llm_api_key",
        "llm_provider",
        "ai_model",
        "llm_api_base",
        "azure_deployment",
        "azure_api_version",
        "google_sheet_sync_enabled",
        "google_sheet_id",
        "google_sheet_tab",
        "google_sheet_sync_user",
        "safe_mode_enabled",
        "global_pause_outreach",
        "pause_new_connection_invites",
        "max_bulk_approve",
        "max_bulk_export",
        "sheet_export_min_confidence_api",
        "sheet_export_min_confidence_after_invite",
    ]
    next_pk = (SiteConfig.objects.order_by("-pk").values_list("pk", flat=True).first() or 0) + 1
    for user in User.objects.filter(is_staff=True):
        if SiteConfig.objects.filter(user_id=user.pk).exists():
            continue
        cfg = SiteConfig(pk=next_pk, user_id=user.pk)
        next_pk += 1
        for field in copy_fields:
            setattr(cfg, field, getattr(global_cfg, field))
        cfg.save(force_insert=True)


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0018_safer_rate_limit_defaults"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfig",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="site_config",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(copy_global_config_to_staff_users, migrations.RunPython.noop),
    ]
