import os
import datetime
from django.test import TestCase
from django.contrib.auth.models import User
from linkedin.models import LinkedInProfile, SiteConfig, Task, Campaign
from linkedin.daemon import run_daemon
from linkedin.exceptions import TaskSkipped
from django.utils import timezone
from unittest.mock import patch, MagicMock

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

class DaemonHardeningTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="daemon_tester")
        self.campaign = Campaign.objects.create(name="Daemon Campaign")
        self.profile = LinkedInProfile.objects.create(
            user=self.user,
            linkedin_username="daemon@example.com",
            linkedin_password="password"
        )
        
    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.timezone.now")
    def test_daemon_skips_task(self, mock_now, mock_diag, mock_handlers):
        # Use a fixed datetime from the standard library to bypass mocks
        fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        mock_now.return_value = fixed_now
        
        # Create a pending task assigned to our campaign
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=fixed_now - datetime.timedelta(minutes=1),
            payload={"campaign_id": self.campaign.pk}
        )
        
        # Mock handler to raise TaskSkipped
        mock_handler = MagicMock(side_effect=TaskSkipped("Rate limited locally"))
        mock_handlers.get.return_value = mock_handler
        
        # Create a mock session
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        
        # Run one iteration of daemon
        # We also need to patch django.utils.timezone.now because Task.objects.claim_next() uses it
        with patch("django.utils.timezone.now", return_value=fixed_now):
            with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    run_daemon(mock_session)
                except KeyboardInterrupt:
                    pass
        
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.SKIPPED)
        self.assertEqual(task.error, "Rate limited locally")

    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.timezone.now")
    def test_daemon_handles_failure(self, mock_now, mock_diag, mock_handlers):
        fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        mock_now.return_value = fixed_now

        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=fixed_now - datetime.timedelta(minutes=1),
            payload={"campaign_id": self.campaign.pk}
        )
        
        mock_handler = MagicMock(side_effect=Exception("Hard failure"))
        mock_handlers.get.return_value = mock_handler
        
        # Create a mock session
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        
        with patch("django.utils.timezone.now", return_value=fixed_now):
            with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    run_daemon(mock_session)
                except KeyboardInterrupt:
                    pass
        
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.FAILED)
        self.assertIn("Hard failure", task.error)

    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.timezone.now")
    def test_daemon_polls_instead_of_consuming_connect_tasks_when_invites_paused(
        self,
        mock_now,
        mock_diag,
        mock_handlers,
    ):
        fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        mock_now.return_value = fixed_now
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=fixed_now - datetime.timedelta(minutes=1),
            payload={"campaign_id": self.campaign.pk},
        )
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]

        with patch("django.utils.timezone.now", return_value=fixed_now):
            with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    run_daemon(mock_session)
                except KeyboardInterrupt:
                    pass

        mock_handlers.get.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.PENDING)

    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.heal_tasks")
    @patch("linkedin.daemon._build_qualifiers", return_value={})
    def test_daemon_only_claims_tasks_for_session_campaigns(
        self,
        _mock_qualifiers,
        _mock_heal_tasks,
        _mock_diag,
        mock_handlers,
    ):
        other_campaign = Campaign.objects.create(name="Other Campaign")
        other_user = User.objects.create_user(username="other_daemon_user")
        other_task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now() - datetime.timedelta(minutes=2),
            payload={"campaign_id": other_campaign.pk, "public_id": "other"},
        )
        ownerless_task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now() - datetime.timedelta(minutes=2),
            payload={"campaign_id": self.campaign.pk, "public_id": "ownerless"},
        )
        wrong_owner_task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now() - datetime.timedelta(minutes=2),
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": "wrong-owner",
                "owner_id": other_user.pk,
            },
        )
        own_task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now() - datetime.timedelta(minutes=1),
            payload={"campaign_id": self.campaign.pk, "public_id": "own", "owner_id": self.user.pk},
        )

        mock_handlers.get.return_value = MagicMock()
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        mock_session.django_user = self.user

        with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
            try:
                run_daemon(mock_session)
            except KeyboardInterrupt:
                pass

        own_task.refresh_from_db()
        other_task.refresh_from_db()
        ownerless_task.refresh_from_db()
        wrong_owner_task.refresh_from_db()
        self.assertEqual(own_task.status, Task.Status.COMPLETED)
        self.assertEqual(other_task.status, Task.Status.PENDING)
        self.assertEqual(ownerless_task.status, Task.Status.PENDING)
        self.assertEqual(wrong_owner_task.status, Task.Status.PENDING)

    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.heal_tasks")
    @patch("linkedin.daemon._build_qualifiers", return_value={})
    def test_daemon_prioritizes_send_message_over_background_tasks(
        self,
        _mock_qualifiers,
        _mock_heal_tasks,
        _mock_diag,
        mock_handlers,
    ):
        older_check = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now() - datetime.timedelta(hours=2),
            payload={"campaign_id": self.campaign.pk, "public_id": "check", "owner_id": self.user.pk},
        )
        send_task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            scheduled_at=timezone.now(),
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": "send",
                "message_id": 123,
                "owner_id": self.user.pk,
            },
        )
        claimed = []

        def handler(task, *_args):
            claimed.append(task.pk)

        mock_handlers.get.return_value = handler
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        mock_session.django_user = self.user

        with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
            try:
                run_daemon(mock_session)
            except KeyboardInterrupt:
                pass

        self.assertGreaterEqual(len(claimed), 2)
        self.assertEqual(claimed[0], send_task.pk)
        self.assertEqual(claimed[1], older_check.pk)

    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.heal_tasks")
    @patch("linkedin.daemon._build_qualifiers", return_value={})
    def test_daemon_does_not_claim_future_scheduled_tasks(
        self,
        _mock_qualifiers,
        _mock_heal_tasks,
        _mock_diag,
        mock_handlers,
    ):
        future_task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now() + datetime.timedelta(hours=2),
            payload={"campaign_id": self.campaign.pk, "public_id": "future", "owner_id": self.user.pk},
        )
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        mock_session.django_user = self.user

        with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
            try:
                run_daemon(mock_session)
            except KeyboardInterrupt:
                pass

        mock_handlers.get.assert_not_called()
        future_task.refresh_from_db()
        self.assertEqual(future_task.status, Task.Status.PENDING)


class RunDaemonCommandTests(TestCase):
    def test_launcher_pid_arg_is_accepted_for_compatibility(self):
        from linkedin.management.commands.rundaemon import Command

        parser = Command().create_parser("manage.py", "rundaemon")
        options = parser.parse_args(["--launcher-pid", "12345"])

        self.assertEqual(options.launcher_pid, 12345)
