# Rename SiteConfig sheet export confidence threshold after follow rename.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("linkedin", "0022_rename_instagram_profile_table"),
    ]

    operations = [
        migrations.RenameField(
            model_name="siteconfig",
            old_name="sheet_export_min_confidence_after_invite",
            new_name="sheet_export_min_confidence_after_follow",
        ),
    ]
