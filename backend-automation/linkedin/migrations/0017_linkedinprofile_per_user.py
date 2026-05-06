"""Per-user LinkedIn profile ownership.

Switches ``LinkedInProfile.user`` from ``OneToOneField`` to ``ForeignKey`` so a
single Django admin/superadmin can own multiple LinkedIn accounts, while still
isolating each owner's accounts from every other admin.

- ``related_name`` flips from ``"linkedin_profile"`` (singular OneToOne accessor)
  to ``"linkedin_profiles"`` (FK manager). No call sites currently use the old
  reverse accessor (audited via grep across the backend), so the rename is safe.
- A ``created_at`` timestamp is introduced for ordering listings most-recent-first.
- ``UniqueConstraint(user, linkedin_username)`` prevents the same Django user
  from accidentally adding the same LinkedIn handle twice. Different Django
  users may independently connect the same LinkedIn handle (e.g. shared
  corporate accounts) — this is intentional.
"""
from __future__ import annotations

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("linkedin", "0016_siteconfig_pause_new_connection_invites"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="linkedinprofile",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="linkedin_profiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="linkedinprofile",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="linkedinprofile",
            constraint=models.UniqueConstraint(
                fields=("user", "linkedin_username"),
                name="uniq_linkedinprofile_user_username",
            ),
        ),
    ]
