# Generated manually for LinkedIn → Instagram conversion

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_task_and_action_values(apps, schema_editor):
    Task = apps.get_model("linkedin", "Task")
    ActionLog = apps.get_model("linkedin", "ActionLog")
    OutreachEvent = apps.get_model("linkedin", "OutreachEvent")
    HistoricalTask = apps.get_model("linkedin", "HistoricalTask")

    Task.objects.filter(task_type="connect").update(task_type="follow")
    HistoricalTask.objects.filter(task_type="connect").update(task_type="follow")
    ActionLog.objects.filter(action_type="connect").update(action_type="follow")

    OutreachEvent.objects.filter(event_type="invite_sent").update(event_type="follow_sent")
    OutreachEvent.objects.filter(event_type="invite_failed").update(event_type="follow_failed")
    OutreachEvent.objects.filter(event_type="connection_detected").update(event_type="follow_back_detected")


def reverse_task_and_action_values(apps, schema_editor):
    Task = apps.get_model("linkedin", "Task")
    ActionLog = apps.get_model("linkedin", "ActionLog")
    OutreachEvent = apps.get_model("linkedin", "OutreachEvent")
    HistoricalTask = apps.get_model("linkedin", "HistoricalTask")

    Task.objects.filter(task_type="follow").update(task_type="connect")
    HistoricalTask.objects.filter(task_type="follow").update(task_type="connect")
    ActionLog.objects.filter(action_type="follow").update(action_type="connect")

    OutreachEvent.objects.filter(event_type="follow_sent").update(event_type="invite_sent")
    OutreachEvent.objects.filter(event_type="follow_failed").update(event_type="invite_failed")
    OutreachEvent.objects.filter(event_type="follow_back_detected").update(event_type="connection_detected")


def migrate_task_payload_keys(apps, schema_editor):
    Task = apps.get_model("linkedin", "Task")
    for task in Task.objects.all().iterator():
        payload = dict(task.payload or {})
        changed = False
        if "linkedin_profile_id" in payload and "instagram_profile_id" not in payload:
            payload["instagram_profile_id"] = payload.pop("linkedin_profile_id")
            changed = True
        elif "linkedin_profile_id" in payload:
            payload.pop("linkedin_profile_id", None)
            changed = True
        if changed:
            task.payload = payload
            task.save(update_fields=["payload"])


def reverse_task_payload_keys(apps, schema_editor):
    Task = apps.get_model("linkedin", "Task")
    for task in Task.objects.all().iterator():
        payload = dict(task.payload or {})
        if "instagram_profile_id" in payload and "linkedin_profile_id" not in payload:
            payload["linkedin_profile_id"] = payload.pop("instagram_profile_id")
            task.payload = payload
            task.save(update_fields=["payload"])


class Migration(migrations.Migration):

    # Ordering note: chat.0006 depends on *this* migration (not the reverse).
    # That way DBs that already applied 0021 can still apply chat.0006, which
    # must FK linkedin.InstagramProfile after the RenameModel below.
    dependencies = [
        ("linkedin", "0020_increase_outreach_capacity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(
            old_name="LinkedInProfile",
            new_name="InstagramProfile",
        ),
        # Preserve the legacy physical table name after RenameModel.
        migrations.AlterModelTable(
            name="instagramprofile",
            table="linkedin_linkedinprofile",
        ),
        migrations.AlterField(
            model_name="instagramprofile",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="instagram_profiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RenameField(
            model_name="instagramprofile",
            old_name="linkedin_username",
            new_name="instagram_username",
        ),
        migrations.RenameField(
            model_name="instagramprofile",
            old_name="linkedin_password",
            new_name="instagram_password",
        ),
        migrations.RenameField(
            model_name="instagramprofile",
            old_name="connect_daily_limit",
            new_name="follow_daily_limit",
        ),
        migrations.RenameField(
            model_name="instagramprofile",
            old_name="connect_weekly_limit",
            new_name="follow_weekly_limit",
        ),
        migrations.RenameField(
            model_name="actionlog",
            old_name="linkedin_profile",
            new_name="instagram_profile",
        ),
        migrations.RenameField(
            model_name="siteconfig",
            old_name="pause_new_connection_invites",
            new_name="pause_new_follows",
        ),
        migrations.AlterField(
            model_name="instagramprofile",
            name="follow_daily_limit",
            field=models.PositiveIntegerField(default=20),
        ),
        migrations.AlterField(
            model_name="instagramprofile",
            name="follow_weekly_limit",
            field=models.PositiveIntegerField(default=80),
        ),
        migrations.AlterField(
            model_name="instagramprofile",
            name="follow_up_daily_limit",
            field=models.PositiveIntegerField(default=15),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="pause_new_follows",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Stops new Instagram follow expansion while allowing monitoring, replies, "
                    "follow-ups, and existing pending follow-back checks to continue."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="google_sheet_tab",
            field=models.CharField(
                blank=True,
                default="Sheet1",
                help_text=(
                    "Tab name (e.g. Sheet1). Rows append to columns A–G: "
                    "Name, Company, Position, Instagram, Followed, Status, Action."
                ),
                max_length=100,
            ),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="sheet_export_min_confidence_api",
            field=models.FloatField(
                default=0.85,
                help_text=(
                    "Minimum follow-back confidence to export when verified via Instagram UI "
                    "(Message available / follows you)."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="sheet_export_min_confidence_after_invite",
            field=models.FloatField(
                default=0.55,
                help_text=(
                    "Minimum confidence for export after a follow_sent event "
                    "(UI Message heuristic or re-check)."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="actionlog",
            name="action_type",
            field=models.CharField(
                choices=[("follow", "Follow"), ("follow_up", "Follow Up")],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="task",
            name="task_type",
            field=models.CharField(
                choices=[
                    ("follow", "follow"),
                    ("check_pending", "check_pending"),
                    ("follow_up", "follow_up"),
                    ("send_message", "send_message"),
                    ("reply_check", "reply_check"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="historicaltask",
            name="task_type",
            field=models.CharField(
                choices=[
                    ("follow", "follow"),
                    ("check_pending", "check_pending"),
                    ("follow_up", "follow_up"),
                    ("send_message", "send_message"),
                    ("reply_check", "reply_check"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="outreachevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("follow_sent", "Follow Sent"),
                    ("follow_failed", "Follow Failed"),
                    ("follow_back_detected", "Follow Back Detected"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.RunPython(migrate_task_and_action_values, reverse_task_and_action_values),
        migrations.RunPython(migrate_task_payload_keys, reverse_task_payload_keys),
        migrations.RemoveConstraint(
            model_name="instagramprofile",
            name="uniq_linkedinprofile_user_username",
        ),
        migrations.AddConstraint(
            model_name="instagramprofile",
            constraint=models.UniqueConstraint(
                fields=("user", "instagram_username"),
                name="uniq_instagramprofile_user_username",
            ),
        ),
        migrations.AlterModelOptions(
            name="instagramprofile",
            options={
                "verbose_name": "Instagram Profile",
                "verbose_name_plural": "Instagram Profiles",
            },
        ),
    ]
