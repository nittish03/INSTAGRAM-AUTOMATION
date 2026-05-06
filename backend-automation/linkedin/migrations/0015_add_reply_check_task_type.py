from django.db import migrations, models


TASK_TYPE_CHOICES = [
    ("connect", "Connect"),
    ("check_pending", "Check Pending"),
    ("follow_up", "Follow Up"),
    ("send_message", "Send Message"),
    ("reply_check", "Reply Check"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("linkedin", "0014_alter_outreachevent_systemrawlog_pk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="task_type",
            field=models.CharField(choices=TASK_TYPE_CHOICES, max_length=20),
        ),
        migrations.AlterField(
            model_name="historicaltask",
            name="task_type",
            field=models.CharField(choices=TASK_TYPE_CHOICES, max_length=20),
        ),
    ]
