from django.test import TestCase
from django.contrib.auth.models import User
from linkedin.models import InstagramProfile, Task, Campaign
from django.utils import timezone
import os
from unittest.mock import patch

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

class ModelHardeningTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.campaign = Campaign.objects.create(name="Test Campaign")

    def test_instagram_profile_encryption(self):
        profile = InstagramProfile.objects.create(
            user=self.user,
            instagram_username="test@example.com",
            instagram_password="secretpassword"
        )
        
        # Verify transparency
        self.assertEqual(profile.instagram_password, "secretpassword")
        
        # Verify DB storage is encrypted
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT instagram_password FROM linkedin_instagramprofile WHERE id=%s", [profile.id])
            raw_value = cursor.fetchone()[0]
            self.assertTrue(raw_value.startswith("gAAAA"))
            self.assertNotEqual(raw_value, "secretpassword")

    def test_task_status_methods(self):
        task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW,
            scheduled_at=timezone.now()
        )
        
        self.assertEqual(task.status, Task.Status.PENDING)
        
        task.mark_running()
        self.assertEqual(task.status, Task.Status.RUNNING)
        self.assertIsNotNone(task.started_at)
        
        task.mark_skipped("Rate limited")
        self.assertEqual(task.status, Task.Status.SKIPPED)
        self.assertEqual(task.error, "Rate limited")
        self.assertIsNotNone(task.ended_at)
        
        task.mark_failed("Fatal error")
        self.assertEqual(task.status, Task.Status.FAILED)
        self.assertEqual(task.error, "Fatal error")
        self.assertIsNotNone(task.ended_at)

    def test_invalid_token_decrypt_fallback_logs_once_at_debug(self):
        import linkedin.models as linkedin_models

        linkedin_models._decrypt_invalid_token_logged = False

        with self.assertLogs("linkedin.models", level="DEBUG") as logs:
            self.assertEqual(linkedin_models.decrypt_value("legacy-plaintext"), "legacy-plaintext")
            self.assertEqual(linkedin_models.decrypt_value("another-legacy-value"), "another-legacy-value")

        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "DEBUG")

    def test_time_limits_env_can_disable_profile_rate_limits(self):
        profile = InstagramProfile.objects.create(
            user=self.user,
            follow_daily_limit=0,
            follow_weekly_limit=0,
            follow_up_daily_limit=0,
        )

        with patch.dict(os.environ, {"BOT_TIME_LIMITS_ENABLED": "true"}):
            self.assertFalse(profile.can_execute("follow"))
            self.assertFalse(profile.can_execute("follow_up"))

        with patch.dict(os.environ, {"BOT_TIME_LIMITS_ENABLED": "false"}):
            self.assertTrue(profile.can_execute("follow"))
            self.assertTrue(profile.can_execute("follow_up"))
