import os
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from chat.models import ChatMessage
from crm.models import Lead
from linkedin.models import InstagramProfile

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class ChatSyncSafetyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="msg_owner")
        self.lead = Lead.objects.create(
            first_name="Neeraj",
            last_name="Kumar",
            public_identifier="neeraj-kumar-target",
            instagram_url="https://www.instagram.com/neeraj-kumar-target/",
            profile_data={"urn": "ig_profile_target"},
        )
        self.lead_ct = ContentType.objects.get_for_model(Lead)
        self.profile = InstagramProfile.objects.create(user=self.user, active=True)

    def test_navigation_conversation_opens_instagram_thread_key(self):
        """Instagram navigation returns thread keys (not legacy URNs)."""
        from linkedin.actions.conversations import find_conversation_urn_via_navigation

        with patch(
            "linkedin.actions.conversations._open_thread_with_user",
            return_value=False,
        ):
            session = MagicMock()
            self.assertIsNone(find_conversation_urn_via_navigation(session, "instagram:missinguser"))

        with patch(
            "linkedin.actions.conversations._open_thread_with_user",
            return_value=True,
        ):
            session = MagicMock()
            self.assertEqual(
                find_conversation_urn_via_navigation(session, "instagram:neeraj-kumar-target"),
                "instagram:thread:neeraj-kumar-target",
            )

    def test_sync_matches_local_sent_placeholder_to_real_message(self):
        from linkedin.db.chat import sync_conversation

        placeholder = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            content="Thanks for connecting.",
            instagram_message_id="sent_local_placeholder",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
            instagram_profile=self.profile,
            creation_date=timezone.now(),
        )
        session = MagicMock()
        session.self_profile = {"urn": "ig_profile_self"}
        session.django_user = self.user
        session.instagram_profile = self.profile

        api_message = {
            "entityUrn": "ig_msg_real",
            "body": {"text": "Thanks for connecting."},
            "sender": {
                "hostIdentityUrn": "ig_profile_self",
                "participantType": {"member": {"firstName": {"text": "Me"}, "lastName": {"text": ""}}},
            },
            "deliveredAt": int(timezone.now().timestamp() * 1000),
        }

        with (
            patch("linkedin.actions.conversations.find_conversation_urn", return_value="ig_thread_target"),
            patch("linkedin.api.messaging.fetch_messages", return_value=[api_message]),
            patch("linkedin.api.client.PlaywrightInstagramAPI"),
        ):
            messages = sync_conversation(session, self.lead.public_identifier, include_drafts=False)

        placeholder.refresh_from_db()
        self.assertEqual(placeholder.instagram_message_id, "ig_msg_real")
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual([m["text"] for m in messages], ["Thanks for connecting."])

    def test_read_from_db_hides_duplicate_sent_placeholder_when_real_message_exists(self):
        from linkedin.db.chat import _read_from_db

        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            content="Same text",
            instagram_message_id="sent_duplicate_placeholder",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
            instagram_profile=self.profile,
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            content="Same text",
            instagram_message_id="ig_msg_real",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
            instagram_profile=self.profile,
        )

        messages = _read_from_db(self.lead, self.lead_ct, owner=self.user, include_drafts=False)

        self.assertEqual([m["text"] for m in messages], ["Same text"])

    def test_follow_up_agent_excludes_drafts_by_default(self):
        from linkedin.agents.follow_up import FollowUpDecision, run_follow_up_agent

        session = MagicMock()
        profile = {"full_name": "Neeraj Kumar"}
        decision = FollowUpDecision(action="wait", follow_up_hours=4)
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = decision
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_llm

        with (
            patch("linkedin.db.chat.sync_conversation", return_value=[]) as mock_sync,
            patch("linkedin.agents.follow_up._render_system_prompt", return_value="prompt"),
            patch("linkedin.agents.follow_up.get_llm_site_config", return_value=MagicMock()),
            patch("linkedin.agents.follow_up.build_chat_llm", return_value=llm),
        ):
            run_follow_up_agent(session, self.lead.public_identifier, profile)

        mock_sync.assert_called_once_with(
            session,
            self.lead.public_identifier,
            include_drafts=False,
        )

    def test_follow_up_agent_waits_when_our_latest_message_is_too_recent(self):
        from linkedin.agents.follow_up import run_follow_up_agent

        session = MagicMock()
        latest = timezone.now() - timedelta(hours=3)
        messages = [
            {
                "sender": "me",
                "text": "Checking in",
                "timestamp": latest.strftime("%Y-%m-%d %H:%M"),
                "timestamp_dt": latest,
                "is_outgoing": True,
            }
        ]

        with (
            patch("linkedin.db.chat.sync_conversation", return_value=messages),
            patch("linkedin.agents.follow_up.build_chat_llm") as mock_llm,
        ):
            decision = run_follow_up_agent(
                session,
                self.lead.public_identifier,
                {"full_name": "Neeraj Kumar"},
                min_follow_up_delay_hours=24,
            )

        self.assertEqual(decision.action, "wait")
        self.assertGreater(decision.follow_up_hours, 20)
        mock_llm.assert_not_called()

    def test_follow_up_agent_passes_discovery_mode_for_empty_conversation(self):
        from linkedin.agents.follow_up import FollowUpDecision, run_follow_up_agent

        session = MagicMock()
        session.campaign = MagicMock(
            product_docs="LTD is a multi-client logistics tracker.",
            campaign_objective="Book demos for LTD.",
            booking_link="https://example.com/book",
        )
        session.self_profile = {"first_name": "Deepali", "last_name": "koli"}
        session.django_user = self.user
        decision = FollowUpDecision(
            action="send_message",
            message="Curious how you keep delivery predictable across clients?",
            follow_up_hours=4,
        )
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = decision
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_llm

        with (
            patch("linkedin.db.chat.sync_conversation", return_value=[]),
            patch("linkedin.agents.follow_up.build_chat_llm", return_value=llm),
        ):
            run_follow_up_agent(session, self.lead.public_identifier, {"full_name": "Neeraj Kumar"})

        prompt = structured_llm.invoke.call_args.args[0]
        self.assertIn("Mode: DISCOVERY", prompt)
        self.assertIn("Follow this messaging skill strictly", prompt)
        self.assertNotIn("## Booking Link", prompt)
        self.assertIn("DISCOVERY mode: first outbound DM", prompt)

    def test_follow_up_agent_passes_reply_mode_for_latest_prospect_message(self):
        from linkedin.agents.follow_up import FollowUpDecision, run_follow_up_agent

        session = MagicMock()
        session.campaign = MagicMock(product_docs="", campaign_objective="", booking_link="")
        session.self_profile = {}
        session.django_user = self.user
        latest = timezone.now()
        messages = [
            {
                "sender": "Neeraj Kumar",
                "text": "Tell me more",
                "timestamp": latest.strftime("%Y-%m-%d %H:%M"),
                "timestamp_dt": latest,
                "is_outgoing": False,
            }
        ]
        decision = FollowUpDecision(action="send_message", message="Sure, happy to.", follow_up_hours=4)
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = decision
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_llm

        with (
            patch("linkedin.db.chat.sync_conversation", return_value=messages),
            patch("linkedin.agents.follow_up.build_chat_llm", return_value=llm),
        ):
            run_follow_up_agent(session, self.lead.public_identifier, {"full_name": "Neeraj Kumar"})

        prompt = structured_llm.invoke.call_args.args[0]
        self.assertIn("Mode: REPLY", prompt)
        self.assertIn("only then relate our product", prompt)

    def test_follow_up_agent_passes_follow_up_mode_after_delay(self):
        from linkedin.agents.follow_up import FollowUpDecision, run_follow_up_agent

        session = MagicMock()
        session.campaign = MagicMock(product_docs="", campaign_objective="", booking_link="")
        session.self_profile = {}
        session.django_user = self.user
        latest = timezone.now() - timedelta(hours=25)
        messages = [
            {
                "sender": "me",
                "text": "Worth exploring?",
                "timestamp": latest.strftime("%Y-%m-%d %H:%M"),
                "timestamp_dt": latest,
                "is_outgoing": True,
            }
        ]
        decision = FollowUpDecision(action="send_message", message="Just checking back on this.", follow_up_hours=4)
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = decision
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_llm

        with (
            patch("linkedin.db.chat.sync_conversation", return_value=messages),
            patch("linkedin.agents.follow_up.build_chat_llm", return_value=llm),
        ):
            run_follow_up_agent(
                session,
                self.lead.public_identifier,
                {"full_name": "Neeraj Kumar"},
                min_follow_up_delay_hours=24,
            )

        prompt = structured_llm.invoke.call_args.args[0]
        self.assertIn("Mode: FOLLOW_UP", prompt)

    def test_follow_up_agent_preserves_previous_conversation_context(self):
        from linkedin.agents.follow_up import FollowUpDecision, run_follow_up_agent

        session = MagicMock()
        session.campaign = MagicMock(product_docs="", campaign_objective="", booking_link="")
        session.self_profile = {}
        session.django_user = self.user
        first_message_at = timezone.now() - timedelta(days=1)
        latest_message_at = timezone.now()
        messages = [
            {
                "sender": "me",
                "text": "Hi Neeraj, noticed your operations work at Acme.",
                "timestamp": first_message_at.strftime("%Y-%m-%d %H:%M"),
                "timestamp_dt": first_message_at,
                "is_outgoing": True,
            },
            {
                "sender": "Neeraj Kumar",
                "text": "We are trying to reduce manual handoffs.",
                "timestamp": latest_message_at.strftime("%Y-%m-%d %H:%M"),
                "timestamp_dt": latest_message_at,
                "is_outgoing": False,
            },
        ]
        decision = FollowUpDecision(action="send_message", message="That context helps.", follow_up_hours=4)
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = decision
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_llm

        with (
            patch("linkedin.db.chat.sync_conversation", return_value=messages),
            patch("linkedin.agents.follow_up.build_chat_llm", return_value=llm),
        ):
            run_follow_up_agent(session, self.lead.public_identifier, {"full_name": "Neeraj Kumar"})

        prompt = structured_llm.invoke.call_args.args[0]
        first_index = prompt.index("Hi Neeraj, noticed your operations work at Acme.")
        latest_index = prompt.index("We are trying to reduce manual handoffs.")
        self.assertLess(first_index, latest_index)
        self.assertIn("Mode: REPLY", prompt)

    def test_send_raw_message_skips_name_search_fallback(self):
        from linkedin.actions.message import send_raw_message

        session = MagicMock()
        profile = {"public_identifier": self.lead.public_identifier, "urn": "ig_profile_target"}

        with (
            patch("linkedin.actions.search._go_to_profile"),
            patch("linkedin.actions.message._send_msg_pop_up", return_value=False),
            patch("linkedin.actions.message.dump_page_html"),
            patch("linkedin.actions.message._send_message") as mock_name_search,
            patch("linkedin.actions.message._send_message_via_api", return_value=True) as mock_api_send,
        ):
            self.assertTrue(send_raw_message(session, profile, "Hello"))

        mock_name_search.assert_not_called()
        mock_api_send.assert_called_once()
