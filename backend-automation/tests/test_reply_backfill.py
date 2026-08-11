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
from linkedin.models import Campaign, InstagramProfile, Task

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class ReplyBackfillTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reply_backfill_owner")
        self.profile = InstagramProfile.objects.create(user=self.user, active=True)
        self.campaign = Campaign.objects.create(
            name="Reply Backfill Campaign",
            product_docs="We help agencies keep delivery on track.",
            campaign_objective="Book qualified calls.",
        )
        self.campaign.users.add(self.user)
        self.lead = Lead.objects.create(
            first_name="Grace",
            last_name="Hopper",
            public_identifier="grace-hopper-reply",
            instagram_url="https://www.instagram.com/grace-hopper-reply/",
            profile_data={
                "public_identifier": "grace-hopper-reply",
                "full_name": "Grace Hopper",
                "urn": "ig_profile_grace_reply",
            },
        )
        self.deal = Deal.objects.create(
            lead=self.lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
        )
        self.lead_ct = ContentType.objects.get_for_model(Lead)

    def _message(self, content: str, *, outgoing: bool, minutes_ago: int):
        return ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content=content,
            instagram_message_id=f"{'out' if outgoing else 'in'}_{minutes_ago}",
            is_outgoing=outgoing,
            is_draft=False,
            is_approved=outgoing,
            owner=self.user,
            creation_date=timezone.now() - timedelta(minutes=minutes_ago),
        )

    def test_process_replied_deal_accelerates_existing_follow_up(self):
        from linkedin.services.reply_backfill import process_replied_deal

        self._message("Want to see it?", outgoing=True, minutes_ago=30)
        self._message("Sure, send details.", outgoing=False, minutes_ago=5)
        follow_up = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            scheduled_at=timezone.now() + timedelta(hours=4),
            deal=self.deal,
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": self.lead.public_identifier,
            },
        )

        with patch("linkedin.db.chat.sync_conversation", return_value=[]):
            result = process_replied_deal(self.deal, MagicMock())

        follow_up.refresh_from_db()
        self.assertEqual(result.status, "accelerated")
        self.assertTrue(result.changed)
        self.assertLessEqual(follow_up.scheduled_at, timezone.now())

    def test_process_replied_deal_skips_when_no_inbound_after_last_outgoing(self):
        from linkedin.services.reply_backfill import process_replied_deal

        self._message("Earlier inbound.", outgoing=False, minutes_ago=60)
        self._message("Our latest reply.", outgoing=True, minutes_ago=5)

        with patch("linkedin.db.chat.sync_conversation", return_value=[]):
            result = process_replied_deal(self.deal, MagicMock())

        self.assertEqual(result.status, "skipped")
        self.assertIn("no inbound reply", result.reason)
        self.assertFalse(
            Task.objects.filter(
                task_type=Task.TaskType.FOLLOW_UP,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )

    def test_process_replied_deal_skips_when_draft_exists(self):
        from linkedin.services.reply_backfill import process_replied_deal

        self._message("Want to see it?", outgoing=True, minutes_ago=30)
        self._message("Yes.", outgoing=False, minutes_ago=5)
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Draft already waiting",
            instagram_message_id="draft_waiting",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
        )

        with patch("linkedin.db.chat.sync_conversation") as mock_sync:
            result = process_replied_deal(self.deal, MagicMock())

        mock_sync.assert_not_called()
        self.assertEqual(result.status, "skipped")
        self.assertIn("draft/send task", result.reason)

    def test_process_replied_deal_dry_run_does_not_change_follow_up(self):
        from linkedin.services.reply_backfill import process_replied_deal

        self._message("Want to see it?", outgoing=True, minutes_ago=30)
        self._message("Sure.", outgoing=False, minutes_ago=5)
        original_schedule = timezone.now() + timedelta(hours=4)
        follow_up = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            scheduled_at=original_schedule,
            deal=self.deal,
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": self.lead.public_identifier,
            },
        )

        with patch("linkedin.db.chat.sync_conversation", return_value=[]):
            result = process_replied_deal(self.deal, MagicMock(), dry_run=True)

        follow_up.refresh_from_db()
        self.assertEqual(result.status, "would_accelerate")
        self.assertEqual(follow_up.scheduled_at, original_schedule)

    def test_process_replied_deal_removes_pending_reply_checks_when_accelerating(self):
        from linkedin.services.reply_backfill import process_replied_deal

        self._message("Want to see it?", outgoing=True, minutes_ago=30)
        self._message("Sure.", outgoing=False, minutes_ago=5)
        Task.objects.create(
            task_type=Task.TaskType.REPLY_CHECK,
            status=Task.Status.PENDING,
            scheduled_at=timezone.now() + timedelta(minutes=10),
            deal=self.deal,
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": self.lead.public_identifier,
                "sent_at": (timezone.now() - timedelta(minutes=30)).isoformat(),
                "attempt": 1,
                "max_attempts": 12,
                "interval_seconds": 600,
                "expires_at": (timezone.now() + timedelta(hours=2)).isoformat(),
            },
        )

        with patch("linkedin.db.chat.sync_conversation", return_value=[]):
            result = process_replied_deal(self.deal, MagicMock())

        self.assertEqual(result.status, "accelerated")
        self.assertFalse(
            Task.objects.filter(
                task_type=Task.TaskType.REPLY_CHECK,
                status=Task.Status.PENDING,
                payload__public_id=self.lead.public_identifier,
            ).exists()
        )
