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
from linkedin.models import Campaign, LinkedInProfile

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class DraftRegenerationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="draft_owner", is_staff=True)
        self.profile = LinkedInProfile.objects.create(user=self.user, active=True)
        self.campaign = Campaign.objects.create(
            name="Draft Campaign",
            product_docs="We help teams reduce manual outreach work.",
            campaign_objective="Book qualified calls.",
        )
        self.campaign.users.add(self.user)
        self.lead = Lead.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            public_identifier="ada-lovelace",
            linkedin_url="https://www.linkedin.com/in/ada-lovelace/",
            profile_data={
                "public_identifier": "ada-lovelace",
                "full_name": "Ada Lovelace",
                "urn": "urn:li:fsd_profile:ada",
            },
        )
        self.deal = Deal.objects.create(
            lead=self.lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
            connection_assessment_source="api_degree_1",
            connection_assessment_confidence=0.95,
        )
        self.lead_ct = ContentType.objects.get_for_model(Lead)

    def test_read_from_db_can_exclude_unsent_drafts(self):
        from linkedin.db.chat import _read_from_db

        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Already sent",
            linkedin_urn="real_message",
            is_outgoing=True,
            is_draft=False,
            owner=self.user,
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old unsent draft",
            linkedin_urn="draft_old",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
            linkedin_profile=self.profile,
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Approved but not sent yet",
            linkedin_urn="draft_approved",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
        )

        messages = _read_from_db(self.lead, self.lead_ct, owner=self.user, include_drafts=False)

        self.assertEqual([m["text"] for m in messages], ["Already sent"])

    def test_drafts_api_includes_latest_real_conversation_message(self):
        self.client.force_login(self.user)
        old_sent_at = timezone.now() - timedelta(hours=3)
        latest_reply_at = timezone.now() - timedelta(minutes=25)
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="I sent this earlier.",
            linkedin_urn="sent_real_context",
            is_outgoing=True,
            is_draft=False,
            owner=self.user,
            linkedin_profile=self.profile,
            creation_date=old_sent_at,
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Can you share more details?",
            linkedin_urn="inbound_real_context",
            is_outgoing=False,
            is_draft=False,
            owner=self.user,
            linkedin_profile=self.profile,
            creation_date=latest_reply_at,
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Approved but not sent yet",
            linkedin_urn="draft_approved_context",
            is_outgoing=True,
            is_draft=False,
            is_approved=True,
            owner=self.user,
            linkedin_profile=self.profile,
            creation_date=timezone.now(),
        )
        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Draft response",
            linkedin_urn="draft_context",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
            linkedin_profile=self.profile,
        )
        other_user = User.objects.create_user(username="other_draft_owner")
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Different account newer reply",
            linkedin_urn="inbound_other_owner_context",
            is_outgoing=False,
            is_draft=False,
            owner=other_user,
            creation_date=timezone.now(),
        )
        ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Other user's draft",
            linkedin_urn="draft_other_context",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=other_user,
        )

        response = self.client.get("/api/messages/drafts/")

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        item = next(row for row in items if row["id"] == draft.id)
        self.assertEqual(item["latestMessage"]["content"], "Can you share more details?")
        self.assertEqual(item["latestMessage"]["createdAt"], latest_reply_at.isoformat())
        self.assertFalse(item["latestMessage"]["isOutgoing"])
        self.assertEqual(item["latestMessage"]["senderLabel"], "Lead")

    def test_drafts_api_requires_staff(self):
        non_staff = User.objects.create_user(username="non_staff_reviewer")
        self.client.force_login(non_staff)

        response = self.client.get("/api/messages/drafts/")

        self.assertEqual(response.status_code, 403)

    def test_regenerate_draft_updates_content_without_approving_or_sending(self):
        from linkedin.services.draft_regeneration import regenerate_draft

        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old draft",
            linkedin_urn="draft_update",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
            linkedin_profile=self.profile,
        )
        decision = MagicMock(action="send_message", message="New better draft")
        session = MagicMock()
        session.campaign = None
        session.django_user = self.user
        session.linkedin_profile = self.profile

        with patch(
            "linkedin.agents.follow_up.run_follow_up_agent",
            return_value=decision,
        ) as mock_agent:
            result = regenerate_draft(draft, session)

        draft.refresh_from_db()
        self.assertEqual(draft.content, "New better draft")
        self.assertTrue(draft.is_draft)
        self.assertFalse(draft.is_approved)
        self.assertEqual(result.status, "updated")
        mock_agent.assert_called_once()
        self.assertFalse(mock_agent.call_args.kwargs["include_drafts"])

    def test_regenerate_draft_dry_run_does_not_save(self):
        from linkedin.services.draft_regeneration import regenerate_draft

        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old draft",
            linkedin_urn="draft_dry_run",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
            linkedin_profile=self.profile,
        )
        decision = MagicMock(action="send_message", message="Dry run draft")
        session = MagicMock()
        session.campaign = None

        with patch("linkedin.agents.follow_up.run_follow_up_agent", return_value=decision):
            result = regenerate_draft(draft, session, dry_run=True)

        draft.refresh_from_db()
        self.assertEqual(draft.content, "Old draft")
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.new_content, "Dry run draft")

    def test_regenerate_draft_keeps_existing_content_when_agent_does_not_send(self):
        from linkedin.services.draft_regeneration import regenerate_draft

        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old draft",
            linkedin_urn="draft_wait",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
        )
        decision = MagicMock(action="wait", message=None, reason=None)
        session = MagicMock()
        session.campaign = None

        with patch("linkedin.agents.follow_up.run_follow_up_agent", return_value=decision):
            result = regenerate_draft(draft, session)

        draft.refresh_from_db()
        self.assertEqual(draft.content, "Old draft")
        self.assertEqual(result.status, "wait")
        self.assertFalse(result.changed)

    def test_regenerate_draft_does_not_overwrite_after_approval_race(self):
        from linkedin.services.draft_regeneration import regenerate_draft

        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Approved content",
            linkedin_urn="draft_race",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
        )
        decision = MagicMock(action="send_message", message="Late regenerated draft")
        session = MagicMock()
        session.campaign = None

        def approve_before_save(*args, **kwargs):
            ChatMessage.objects.filter(pk=draft.pk).update(is_draft=False, is_approved=True)
            return decision

        with patch("linkedin.agents.follow_up.run_follow_up_agent", side_effect=approve_before_save):
            result = regenerate_draft(draft, session)

        draft.refresh_from_db()
        self.assertEqual(draft.content, "Approved content")
        self.assertFalse(draft.is_draft)
        self.assertTrue(draft.is_approved)
        self.assertEqual(result.status, "stale")

    def test_regenerate_draft_does_not_overwrite_manual_edit_race(self):
        from linkedin.services.draft_regeneration import regenerate_draft

        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Original draft",
            linkedin_urn="draft_edit_race",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
        )
        decision = MagicMock(action="send_message", message="Late regenerated draft")
        session = MagicMock()
        session.campaign = None

        def edit_before_save(*args, **kwargs):
            ChatMessage.objects.filter(pk=draft.pk).update(content="Human edited draft")
            return decision

        with patch("linkedin.agents.follow_up.run_follow_up_agent", side_effect=edit_before_save):
            result = regenerate_draft(draft, session)

        draft.refresh_from_db()
        self.assertEqual(draft.content, "Human edited draft")
        self.assertTrue(draft.is_draft)
        self.assertFalse(draft.is_approved)
        self.assertEqual(result.status, "stale")

    def test_regenerate_draft_rejects_ambiguous_missing_campaign(self):
        from linkedin.services.draft_regeneration import regenerate_draft

        other_campaign = Campaign.objects.create(name="Other Campaign")
        Deal.objects.create(
            lead=self.lead,
            campaign=other_campaign,
            state=ProfileState.CONNECTED.value,
        )
        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            content="Legacy draft",
            linkedin_urn="draft_no_campaign",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
        )

        with self.assertRaisesRegex(ValueError, "ambiguous campaign context"):
            regenerate_draft(draft, MagicMock())

    def test_regenerate_draft_api_updates_single_draft(self):
        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old draft",
            linkedin_urn="draft_api",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
            linkedin_profile=self.profile,
        )
        self.client.force_login(self.user)

        result = MagicMock(
            status="updated",
            changed=True,
            reason="",
            old_content="Old draft",
        )

        def fake_regenerate(d, _session):
            d.content = "API regenerated draft"
            d.save(update_fields=["content"])
            return result

        with (
            patch("linkedin.llm.validate_llm_site_config", return_value=(True, "")),
            patch("linkedin.browser.registry.get_or_create_session", return_value=MagicMock()),
            patch("linkedin.services.draft_regeneration.regenerate_draft", side_effect=fake_regenerate),
        ):
            response = self.client.post(f"/api/messages/drafts/{draft.pk}/regenerate/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["content"], "API regenerated draft")

    def test_regenerate_draft_api_requires_active_profile_for_draft_owner(self):
        other_user = User.objects.create_user(username="other_active")
        LinkedInProfile.objects.create(user=other_user, active=True)
        self.profile.active = False
        self.profile.save(update_fields=["active"])
        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old draft",
            linkedin_urn="draft_api_no_profile",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
        )
        self.client.force_login(self.user)

        with patch("linkedin.llm.validate_llm_site_config", return_value=(True, "")):
            response = self.client.post(f"/api/messages/drafts/{draft.pk}/regenerate/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("draft owner", response.json()["error"])

    def test_regenerate_draft_api_handles_stale_delete_race(self):
        draft = ChatMessage.objects.create(
            content_type=self.lead_ct,
            object_id=self.lead.pk,
            campaign=self.campaign,
            content="Old draft",
            linkedin_urn="draft_api_stale",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
            owner=self.user,
            linkedin_profile=self.profile,
        )
        self.client.force_login(self.user)
        result = MagicMock(
            status="stale",
            changed=False,
            reason="Draft was approved, edited, sent, or deleted during regeneration.",
            old_content="Old draft",
        )

        def fake_regenerate(d, _session):
            d.delete()
            return result

        with (
            patch("linkedin.llm.validate_llm_site_config", return_value=(True, "")),
            patch("linkedin.browser.registry.get_or_create_session", return_value=MagicMock()),
            patch("linkedin.services.draft_regeneration.regenerate_draft", side_effect=fake_regenerate),
        ):
            response = self.client.post(f"/api/messages/drafts/{draft.pk}/regenerate/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "stale")
