import os
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from chat.models import ChatMessage
from crm.models import Deal, Lead
from linkedin.enums import ProfileState
from linkedin.models import Campaign, LinkedInProfile, SiteConfig, Task

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class ReplyCheckTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reply_owner")
        self.profile = LinkedInProfile.objects.create(user=self.user, active=True)
        self.campaign = Campaign.objects.create(
            name="Reply Campaign",
            product_docs="We help agencies keep project delivery on track.",
            campaign_objective="Book qualified calls.",
        )
        self.campaign.users.add(self.user)
        self.lead = Lead.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            public_identifier="ada-lovelace-reply",
            linkedin_url="https://www.linkedin.com/in/ada-lovelace-reply/",
            profile_data={
                "public_identifier": "ada-lovelace-reply",
                "full_name": "Ada Lovelace",
                "urn": "urn:li:fsd_profile:ada-reply",
            },
        )
        self.deal = Deal.objects.create(
            lead=self.lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
        )
        self.lead_ct = ContentType.objects.get_for_model(Lead)

    def _session(self):
        session = MagicMock()
        session.campaign = self.campaign
        session.django_user = self.user
        session.linkedin_profile = self.profile
        session.page = MagicMock()
        return session

    def test_send_message_schedules_capped_reply_check_and_normal_follow_up(self):
        from linkedin.conf import CAMPAIGN_CONFIG
        from linkedin.tasks.send_message import handle_send_message
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])

        msg = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Worth taking a look?",
            linkedin_urn="draft_send",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
        )
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "message_id": msg.pk,
            }
        )

        with patch("linkedin.actions.message.send_raw_message", return_value=True), patch(
            "linkedin.tasks.send_message.get_profile_dict_for_public_id",
            return_value={"profile": self.lead.profile_data},
        ):
            handle_send_message(task, self._session())

        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.FOLLOW_UP,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )
        reply_check = Task.objects.get(
            task_type=Task.TaskType.REPLY_CHECK,
            payload__public_id=self.lead.public_identifier,
        )
        self.assertEqual(reply_check.payload["attempt"], 1)
        self.assertEqual(reply_check.payload["max_attempts"], CAMPAIGN_CONFIG["reply_check_max_attempts"])
        self.assertEqual(reply_check.payload["interval_seconds"], CAMPAIGN_CONFIG["reply_check_interval_seconds"])
        self.assertEqual(reply_check.payload["sent_message_id"], msg.pk)
        self.assertIn("sent_at", reply_check.payload)
        self.assertIn("expires_at", reply_check.payload)

    def test_send_message_uses_profile_ui_send_path(self):
        from linkedin.exceptions import TaskSkipped
        from linkedin.tasks.send_message import handle_send_message

        msg = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Worth taking a look?",
            linkedin_urn="draft_send_ui",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
        )
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "message_id": msg.pk,
            }
        )
        with patch(
            "linkedin.tasks.send_message.get_profile_dict_for_public_id",
            return_value={"profile": self.lead.profile_data},
        ), patch("linkedin.actions.message.send_raw_message", return_value=False) as mock_send:
            with self.assertRaisesRegex(TaskSkipped, "approved message requeued"):
                handle_send_message(task, self._session())

        mock_send.assert_called_once()
        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.SEND_MESSAGE,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
                payload__message_id=msg.pk,
            ).exists()
        )

    def test_send_message_requeues_transient_linkedin_timeout(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from linkedin.exceptions import TaskSkipped
        from linkedin.tasks.send_message import handle_send_message

        msg = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Worth taking a look?",
            linkedin_urn="draft_send_timeout",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
        )
        task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            status=Task.Status.RUNNING,
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "message_id": msg.pk,
                "owner_id": self.user.pk,
            },
            scheduled_at=timezone.now(),
        )

        with patch(
            "linkedin.tasks.send_message.get_profile_dict_for_public_id",
            return_value={"profile": self.lead.profile_data},
        ), patch(
            "linkedin.actions.message.send_raw_message",
            side_effect=PlaywrightTimeoutError(
                "Page.goto: Timeout 30000ms exceeded."
            ),
        ):
            with self.assertRaisesRegex(TaskSkipped, "timed out"):
                handle_send_message(task, self._session())

        retry = Task.objects.get(
            task_type=Task.TaskType.SEND_MESSAGE,
            status=Task.Status.PENDING,
            payload__public_id=self.lead.public_identifier,
            payload__message_id=msg.pk,
        )
        self.assertNotEqual(retry.pk, task.pk)
        self.assertGreater(retry.scheduled_at, timezone.now())
        msg.refresh_from_db()
        self.assertTrue(msg.is_approved)
        self.assertFalse(msg.is_draft)

    def test_send_message_connects_and_requeues_when_profile_shows_connect(self):
        from linkedin.exceptions import TaskSkipped
        from linkedin.tasks.send_message import handle_send_message

        msg = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Worth taking a look?",
            linkedin_urn="draft_send_after_connect",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
        )
        task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            status=Task.Status.RUNNING,
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "message_id": msg.pk,
                "owner_id": self.user.pk,
            },
            scheduled_at=timezone.now(),
        )

        with patch(
            "linkedin.tasks.send_message.get_profile_dict_for_public_id",
            return_value={"profile": self.lead.profile_data},
        ), patch(
            "linkedin.actions.message.send_raw_message",
            side_effect=TaskSkipped("LinkedIn still shows Connect; skipping message send"),
        ), patch(
            "linkedin.actions.connect.send_connection_request",
            return_value=ProfileState.PENDING,
        ) as mock_connect:
            with self.assertRaisesRegex(TaskSkipped, "sent connection invite"):
                handle_send_message(task, self._session())

        mock_connect.assert_called_once()
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.state, ProfileState.PENDING)
        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.CHECK_PENDING,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )
        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.SEND_MESSAGE,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
                payload__message_id=msg.pk,
            )
            .exclude(pk=task.pk)
            .exists()
        )

    def test_reply_check_continues_when_new_invites_are_paused(self):
        from linkedin.tasks.reply_check import handle_reply_check
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        sent_at = timezone.now()
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "sent_at": sent_at.isoformat(),
                "attempt": 1,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (sent_at + timedelta(hours=2)).isoformat(),
            }
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Our last message",
            linkedin_urn="sent_paused_mode",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
            creation_date=sent_at,
        )

        with patch("linkedin.db.chat.sync_conversation", return_value=[]) as mock_sync:
            handle_reply_check(task, self._session())

        mock_sync.assert_called_once()
        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.REPLY_CHECK,
                payload__public_id=self.lead.public_identifier,
                payload__attempt=2,
            ).exists()
        )

    def test_reply_check_reschedules_when_no_reply_and_under_cap(self):
        from linkedin.tasks.reply_check import handle_reply_check

        sent_at = timezone.now()
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "sent_at": sent_at.isoformat(),
                "attempt": 1,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (sent_at + timedelta(hours=2)).isoformat(),
            }
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Our last message",
            linkedin_urn="sent_last",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
            creation_date=sent_at,
        )

        with patch("linkedin.db.chat.sync_conversation", return_value=[]):
            handle_reply_check(task, self._session())

        next_check = Task.objects.get(
            task_type=Task.TaskType.REPLY_CHECK,
            payload__public_id=self.lead.public_identifier,
        )
        self.assertEqual(next_check.payload["attempt"], 2)
        self.assertGreater(next_check.scheduled_at, timezone.now())

    def test_reply_check_accelerates_follow_up_when_reply_arrives(self):
        from linkedin.tasks.reply_check import handle_reply_check

        sent_at = timezone.now() - timedelta(minutes=20)
        follow_up = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            scheduled_at=timezone.now() + timedelta(hours=4),
            deal=self.deal,
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
            },
        )
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "sent_at": sent_at.isoformat(),
                "attempt": 2,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (sent_at + timedelta(hours=2)).isoformat(),
            }
        )

        def add_inbound(*args, **kwargs):
            ChatMessage.objects.create(
                content_type=self.lead_ct,
                object_id=self.lead.pk,
                campaign=self.campaign,
                content="Yes, interested.",
                linkedin_urn="inbound_reply",
                is_outgoing=False,
                is_draft=False,
                owner=self.user,
                creation_date=timezone.now(),
            )
            return []

        with patch("linkedin.db.chat.sync_conversation", side_effect=add_inbound):
            handle_reply_check(task, self._session())

        follow_up.refresh_from_db()
        self.assertLessEqual(follow_up.scheduled_at, timezone.now())
        self.assertFalse(
            Task.objects.filter(
                task_type=Task.TaskType.REPLY_CHECK,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )

    def test_reply_check_stops_at_cap_without_rescheduling(self):
        from linkedin.tasks.reply_check import handle_reply_check

        sent_at = timezone.now() - timedelta(hours=1)
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "sent_at": sent_at.isoformat(),
                "attempt": 12,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (sent_at + timedelta(hours=2)).isoformat(),
            }
        )

        with patch("linkedin.db.chat.sync_conversation", return_value=[]):
            handle_reply_check(task, self._session())

        self.assertFalse(
            Task.objects.filter(
                task_type=Task.TaskType.REPLY_CHECK,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )

    def test_reply_check_stops_expired_window_before_syncing(self):
        from linkedin.tasks.reply_check import handle_reply_check

        sent_at = timezone.now() - timedelta(hours=3)
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "sent_at": sent_at.isoformat(),
                "attempt": 3,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
            }
        )

        with patch("linkedin.db.chat.sync_conversation") as mock_sync:
            handle_reply_check(task, self._session())

        mock_sync.assert_not_called()
        self.assertFalse(
            Task.objects.filter(
                task_type=Task.TaskType.REPLY_CHECK,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )

    def test_reply_check_stops_when_next_check_would_exceed_window(self):
        from linkedin.tasks.reply_check import handle_reply_check

        sent_at = timezone.now() - timedelta(hours=1, minutes=55)
        task = MagicMock(
            payload={
                "public_id": self.lead.public_identifier,
                "campaign_id": self.campaign.pk,
                "sent_at": sent_at.isoformat(),
                "attempt": 11,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (sent_at + timedelta(hours=2)).isoformat(),
            }
        )

        with patch("linkedin.db.chat.sync_conversation") as mock_sync:
            handle_reply_check(task, self._session())

        mock_sync.assert_called_once()
        self.assertFalse(
            Task.objects.filter(
                task_type=Task.TaskType.REPLY_CHECK,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )
