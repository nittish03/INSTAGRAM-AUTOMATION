# Rename physical Instagram profile table away from linkedin_linkedinprofile.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("linkedin", "0021_instagram_conversion"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="instagramprofile",
            table="linkedin_instagramprofile",
        ),
    ]
