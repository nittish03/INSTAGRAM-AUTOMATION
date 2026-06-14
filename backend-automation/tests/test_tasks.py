import os
from django.test import TestCase
from django.utils import timezone
from unittest.mock import MagicMock, patch
from linkedin.models import ActionLog, OutreachEvent, SiteConfig, Task, Campaign, LinkedInProfile
from crm.models import Lead, Deal
from linkedin.tasks.connect import handle_connect, enqueue_connect
from linkedin.exceptions import TaskSkipped, ReachedConnectionLimit
from linkedin.enums import ProfileState

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

class TaskHardeningTest(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(name="Test Campaign")
        # Need a user for LinkedInProfile
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username="testuser")
        self.profile = LinkedInProfile.objects.create(user=self.user)
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = False
        cfg.global_pause_outreach = False
        cfg.save(update_fields=["pause_new_connection_invites", "global_pause_outreach"])
        
    def test_enqueue_connect_with_deal(self):
        lead = Lead.objects.create(
            first_name="John", 
            last_name="Doe", 
            public_identifier="johndoe",
            linkedin_url="https://www.linkedin.com/in/johndoe/"
        )
        deal = Deal.objects.create(lead=lead, campaign=self.campaign)
        
        enqueue_connect(self.campaign.id, delay_seconds=10, deal=deal)
        
        task = Task.objects.get(task_type=Task.TaskType.CONNECT)
        self.assertEqual(task.deal, deal)
        self.assertEqual(task.payload['campaign_id'], self.campaign.id)

    def test_time_limits_env_zeros_bot_pacing_delays(self):
        from linkedin.tasks.connect import enqueue_follow_up

        lead = Lead.objects.create(public_identifier="delay-toggle")
        deal = Deal.objects.create(lead=lead, campaign=self.campaign, state=ProfileState.CONNECTED.value)

        with patch.dict(os.environ, {"BOT_TIME_LIMITS_ENABLED": "false"}):
            before = timezone.now()
            enqueue_connect(self.campaign.id, delay_seconds=3600, deal=deal)
            enqueue_follow_up(self.campaign.id, "delay-toggle", delay_seconds=3600, deal=deal)

        tasks = Task.objects.order_by("scheduled_at")
        self.assertEqual(tasks.count(), 2)
        for task in tasks:
            self.assertLessEqual((task.scheduled_at - before).total_seconds(), 1)

    def test_time_limits_env_can_preserve_external_retry_delay(self):
        with patch.dict(os.environ, {"BOT_TIME_LIMITS_ENABLED": "false"}):
            before = timezone.now()
            enqueue_connect(self.campaign.id, delay_seconds=3600, apply_time_limits=False)

        task = Task.objects.get(task_type=Task.TaskType.CONNECT)
        self.assertGreaterEqual((task.scheduled_at - before).total_seconds(), 3500)

    def test_pause_new_connection_invites_skips_connect_enqueue_only(self):
        from linkedin.tasks.connect import enqueue_check_pending, enqueue_follow_up, enqueue_reply_check

        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        lead = Lead.objects.create(public_identifier="warm-lead")
        deal = Deal.objects.create(lead=lead, campaign=self.campaign, state=ProfileState.PENDING.value)

        enqueue_connect(self.campaign.id, delay_seconds=0)
        enqueue_check_pending(self.campaign.id, "warm-lead", backoff_hours=1, deal=deal)
        enqueue_follow_up(self.campaign.id, "warm-lead", delay_seconds=0, deal=deal)
        enqueue_reply_check(self.campaign.id, "warm-lead", delay_seconds=0, deal=deal)

        self.assertFalse(Task.objects.filter(task_type=Task.TaskType.CONNECT).exists())
        self.assertTrue(Task.objects.filter(task_type=Task.TaskType.CHECK_PENDING).exists())
        self.assertTrue(Task.objects.filter(task_type=Task.TaskType.FOLLOW_UP).exists())
        self.assertTrue(Task.objects.filter(task_type=Task.TaskType.REPLY_CHECK).exists())

    def test_handle_connect_paused_skips_before_fresh_invite_side_effects(self):
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=timezone.now(),
            started_at=timezone.now(),
            payload={"campaign_id": self.campaign.id},
        )
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile

        with (
            patch("linkedin.tasks.connect.strategy_for") as mock_strategy_for,
            patch.object(LinkedInProfile, "can_execute", return_value=True) as mock_can_execute,
            patch("linkedin.actions.connect.send_connection_request") as mock_send,
            patch("google_integration.sheet_sync.sync_pending_lead_to_google_sheet") as mock_sheet_sync,
        ):
            with self.assertRaises(TaskSkipped):
                handle_connect(task, session, {})

        mock_strategy_for.assert_not_called()
        mock_can_execute.assert_not_called()
        mock_send.assert_not_called()
        mock_sheet_sync.assert_not_called()
        self.assertFalse(OutreachEvent.objects.filter(event_type=OutreachEvent.EventType.INVITE_SENT).exists())
        self.assertFalse(
            ActionLog.objects.filter(action_type=ActionLog.ActionType.CONNECT, status="success").exists()
        )
        self.assertEqual(Task.objects.filter(task_type=Task.TaskType.CONNECT).count(), 1)

    def test_handle_connect_paused_does_not_create_freemium_deal(self):
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        self.campaign.is_freemium = True
        self.campaign.save(update_fields=["is_freemium"])
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=timezone.now(),
            started_at=timezone.now(),
            payload={"campaign_id": self.campaign.id},
        )
        session = MagicMock(campaign=self.campaign, linkedin_profile=self.profile)

        with patch("linkedin.db.deals.create_freemium_deal") as mock_create_deal:
            with self.assertRaises(TaskSkipped):
                handle_connect(task, session, {})

        mock_create_deal.assert_not_called()
        self.assertFalse(Deal.objects.filter(campaign=self.campaign).exists())

    def test_heal_tasks_paused_skips_connect_seed_but_preserves_monitoring(self):
        from linkedin.daemon import heal_tasks

        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        pending_lead = Lead.objects.create(
            public_identifier="pending-monitor",
            linkedin_url="https://www.linkedin.com/in/pending-monitor/",
        )
        pending_deal = Deal.objects.create(
            lead=pending_lead,
            campaign=self.campaign,
            state=ProfileState.PENDING.value,
            backoff_hours=1,
        )
        connected_lead = Lead.objects.create(
            public_identifier="connected-warm",
            linkedin_url="https://www.linkedin.com/in/connected-warm/",
        )
        connected_deal = Deal.objects.create(
            lead=connected_lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
            connection_assessment_source="api_degree_1",
            connection_assessment_confidence=0.95,
        )
        running_task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.RUNNING,
            scheduled_at=timezone.now(),
            deal=connected_deal,
            payload={"campaign_id": self.campaign.id, "public_id": connected_lead.public_identifier},
        )
        session = MagicMock(campaigns=[self.campaign], campaign=self.campaign)

        heal_tasks(session)

        running_task.refresh_from_db()
        self.assertEqual(running_task.status, Task.Status.PENDING)
        self.assertFalse(Task.objects.filter(task_type=Task.TaskType.CONNECT).exists())
        self.assertTrue(Task.objects.filter(task_type=Task.TaskType.CHECK_PENDING, deal=pending_deal).exists())
        self.assertTrue(Task.objects.filter(task_type=Task.TaskType.FOLLOW_UP, deal=connected_deal).exists())

    def test_task_queue_ignores_due_connect_tasks_while_paused(self):
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        connect_task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=timezone.now(),
            payload={"campaign_id": self.campaign.id},
        )
        monitor_task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            scheduled_at=timezone.now(),
            payload={"campaign_id": self.campaign.id, "public_id": "already-pending"},
        )

        self.assertEqual(Task.objects.claim_next(), monitor_task)
        connect_task.refresh_from_db()
        self.assertEqual(connect_task.status, Task.Status.PENDING)

        cfg.pause_new_connection_invites = False
        cfg.save(update_fields=["pause_new_connection_invites"])
        monitor_task.delete()
        self.assertEqual(Task.objects.claim_next(), connect_task)

    @patch('linkedin.tasks.connect.strategy_for')
    def test_handle_connect_rate_limit(self, mock_strategy_for):
        # Setup mocks
        mock_strategy = MagicMock()
        mock_strategy_for.return_value = mock_strategy
        
        # strategy_for is mocked to avoid DB lookups for qualifiers.
        # find_candidate is never reached because can_execute=False fires first.
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=timezone.now(),
            started_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        
        # Mock can_execute to return False (simulating rate limit)
        with patch.object(LinkedInProfile, 'can_execute', return_value=False):
            with self.assertRaises(TaskSkipped):
                handle_connect(task, session, {})
        
        # Verify a new task was enqueued
        # There should be the original task and a new one
        self.assertEqual(Task.objects.count(), 2)
        new_task = Task.objects.exclude(id=task.id).first()
        self.assertEqual(new_task.status, Task.Status.PENDING)
        self.assertEqual(new_task.task_type, Task.TaskType.CONNECT)

    def test_check_pending_expiry(self):
        # [NEW-CRIT-01] Test 30-day age limit logic
        from datetime import timedelta
        from linkedin.tasks.check_pending import handle_check_pending
        from linkedin.enums import ProfileState
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])
        
        lead = Lead.objects.create(public_identifier="old_guy")
        deal = Deal.objects.create(lead=lead, campaign=self.campaign)
        
        # Manually backdate creation_date
        old_date = timezone.now() - timedelta(days=31)
        Deal.objects.filter(pk=deal.pk).update(creation_date=old_date)
        deal.refresh_from_db()
        
        task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            payload={"campaign_id": self.campaign.id, "public_id": "old_guy"},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        
        handle_check_pending(task, session, {})
        
        deal.refresh_from_db()
        self.assertEqual(deal.state, ProfileState.FAILED)
        self.assertIn("Expired", deal.reason)

    def test_check_pending_transient_profile_issue_keeps_pending(self):
        from linkedin.exceptions import SkipProfile
        from linkedin.tasks.check_pending import handle_check_pending

        lead = Lead.objects.create(public_identifier="pending-glitch")
        deal = Deal.objects.create(
            lead=lead,
            campaign=self.campaign,
            state=ProfileState.PENDING.value,
            backoff_hours=1,
        )
        task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            status=Task.Status.RUNNING,
            payload={
                "campaign_id": self.campaign.id,
                "public_id": "pending-glitch",
                "backoff_hours": 1,
            },
            scheduled_at=timezone.now(),
        )
        session = MagicMock()
        session.campaign = self.campaign

        with patch(
            "linkedin.actions.status.get_connection_assessment",
            side_effect=SkipProfile("Top Card section not found"),
        ):
            handle_check_pending(task, session, {})

        deal.refresh_from_db()
        self.assertEqual(deal.state, ProfileState.PENDING)
        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.CHECK_PENDING,
                status=Task.Status.PENDING,
                payload__public_id="pending-glitch",
            ).exists()
        )

    def test_send_message_missing_data(self):
        # [MED-06] send_message: ChatMessage or Deal missing
        from linkedin.tasks.send_message import handle_send_message
        
        task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            payload={"campaign_id": self.campaign.id, "public_id": "who", "message_id": 9999},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        
        with self.assertRaisesRegex(RuntimeError, "ChatMessage 9999 is not available"):
            handle_send_message(task, session)

    def test_send_message_missing_deal(self):
        # [MED-06] send_message: Deal missing
        from linkedin.tasks.send_message import handle_send_message
        from chat.models import ChatMessage
        
        msg = ChatMessage.objects.create(
            content="Hello", 
            linkedin_urn="test_urn",
            content_type_id=1,
            object_id=1,  # dummy
            owner=self.user,
            linkedin_profile=self.profile,
        )
        
        task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            payload={"campaign_id": self.campaign.id, "public_id": "missing_deal", "message_id": msg.pk},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        
        with self.assertRaisesRegex(RuntimeError, "No Deal found"):
            handle_send_message(task, session)

    def test_freemium_model_loading(self):
        # [HIGH-01] Test freemium model loading logic in dairy builder
        from linkedin.daemon import _build_qualifiers
        
        self.campaign.is_freemium = True
        self.campaign.save()
        
        # Mock load_ml_model to return a dummy model
        mock_model = MagicMock()
        with patch.object(Campaign, 'load_ml_model', return_value=mock_model):
            qualifiers = _build_qualifiers([self.campaign], {"qualification_n_mc_samples": 100})
            
            self.assertIn(self.campaign.pk, qualifiers)
            self.assertEqual(qualifiers[self.campaign.pk]._model, mock_model)

    def test_follow_up_dedup_guard(self):
        # Verify follow_up keeps a single pending draft until admin approval.
        from linkedin.tasks.follow_up import handle_follow_up
        from chat.models import ChatMessage
        cfg = SiteConfig.load()
        cfg.pause_new_connection_invites = True
        cfg.save(update_fields=["pause_new_connection_invites"])

        from linkedin.enums import ProfileState
        lead = Lead.objects.create(public_identifier="dedup_test")
        Deal.objects.create(lead=lead, campaign=self.campaign, state=ProfileState.CONNECTED.value)

        task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            payload={"campaign_id": self.campaign.id, "public_id": "dedup_test"},
            scheduled_at=timezone.now()
        )

        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile

        decision = MagicMock()
        decision.action = "send_message"
        decision.message = "Hello again"

        assessment = MagicMock(state=ProfileState.CONNECTED, source="api_degree_1", confidence=0.95)
        with patch("linkedin.actions.status.get_connection_assessment", return_value=assessment), patch(
            'linkedin.agents.follow_up.run_follow_up_agent',
            return_value=decision,
        ):
            handle_follow_up(task, session, {})
            self.assertEqual(ChatMessage.objects.filter(is_draft=True).count(), 1)
            self.assertEqual(ChatMessage.objects.filter(is_approved=True).count(), 0)

            handle_follow_up(task, session, {})
            self.assertEqual(ChatMessage.objects.filter(is_draft=True).count(), 1)
            self.assertEqual(ChatMessage.objects.filter(is_approved=True).count(), 0)

    def test_follow_up_quota_error_reschedules(self):
        from linkedin.tasks.follow_up import handle_follow_up

        lead = Lead.objects.create(public_identifier="quota_follow_up")
        deal = Deal.objects.create(lead=lead, campaign=self.campaign, state=ProfileState.CONNECTED.value)
        task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.RUNNING,
            payload={"campaign_id": self.campaign.id, "public_id": "quota_follow_up"},
            scheduled_at=timezone.now(),
        )
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        quota_error = Exception(
            "429 RESOURCE_EXHAUSTED generate_content_free_tier_requests Please retry in 46.0s"
        )

        assessment = MagicMock(state=ProfileState.CONNECTED, source="api_degree_1", confidence=0.95)
        with patch("linkedin.actions.status.get_connection_assessment", return_value=assessment), patch(
            "linkedin.agents.follow_up.run_follow_up_agent",
            side_effect=quota_error,
        ):
            with self.assertRaisesRegex(TaskSkipped, "quota exhausted"):
                handle_follow_up(task, session, {})

        self.assertTrue(
            Task.objects.filter(
                task_type=Task.TaskType.FOLLOW_UP,
                status=Task.Status.PENDING,
                deal=deal,
                payload__public_id="quota_follow_up",
            ).exists()
        )

    def test_follow_up_does_not_draft_when_not_connected(self):
        from chat.models import ChatMessage
        from linkedin.tasks.follow_up import handle_follow_up

        lead = Lead.objects.create(public_identifier="not_connected_follow_up")
        deal = Deal.objects.create(
            lead=lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
            backoff_hours=1,
        )
        task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            payload={"campaign_id": self.campaign.id, "public_id": "not_connected_follow_up"},
            scheduled_at=timezone.now(),
        )
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        assessment = MagicMock(state=ProfileState.QUALIFIED, source="ui_connect_visible", confidence=0.8)

        with patch("linkedin.actions.status.get_connection_assessment", return_value=assessment), patch(
            "linkedin.agents.follow_up.run_follow_up_agent",
        ) as mock_agent:
            with self.assertRaisesRegex(TaskSkipped, "requires an API-verified connected profile"):
                handle_follow_up(task, session, {})

        mock_agent.assert_not_called()
        deal.refresh_from_db()
        self.assertEqual(deal.state, ProfileState.QUALIFIED)
        self.assertFalse(ChatMessage.objects.filter(object_id=lead.pk, is_draft=True).exists())

    def test_message_drafts_api_only_shows_connected_deal_drafts(self):
        import json
        from datetime import timedelta
        from django.contrib.contenttypes.models import ContentType
        from django.test import RequestFactory
        from linkedin.views import api_message_drafts, api_message_drafts_approve, api_messaging_diagnostics
        from chat.models import ChatMessage

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.campaign.users.add(self.user)
        lead_ct = ContentType.objects.get_for_model(Lead)
        connected_lead = Lead.objects.create(
            public_identifier="connected-draft",
            linkedin_url="https://www.linkedin.com/in/connected-draft/",
        )
        pending_lead = Lead.objects.create(
            public_identifier="pending-draft",
            linkedin_url="https://www.linkedin.com/in/pending-draft/",
        )
        other_profile_lead = Lead.objects.create(
            public_identifier="other-profile-draft",
            linkedin_url="https://www.linkedin.com/in/other-profile-draft/",
        )
        other_profile = LinkedInProfile.objects.create(
            user=self.user,
            linkedin_username="other-profile@example.com",
            active=False,
        )
        connected_deal = Deal.objects.create(
            lead=connected_lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
            connection_assessment_source="api_degree_1",
            connection_assessment_confidence=0.95,
        )
        Deal.objects.create(
            lead=pending_lead,
            campaign=self.campaign,
            state=ProfileState.PENDING.value,
        )
        Deal.objects.create(
            lead=other_profile_lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
            connection_assessment_source="api_degree_1",
            connection_assessment_confidence=0.95,
        )
        connected_draft = ChatMessage.objects.create(
            content_type=lead_ct,
            object_id=connected_lead.pk,
            campaign=self.campaign,
            owner=self.user,
            linkedin_profile=self.profile,
            content="Connected draft",
            linkedin_urn="draft_connected_visible",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
        )
        pending_draft = ChatMessage.objects.create(
            content_type=lead_ct,
            object_id=pending_lead.pk,
            campaign=self.campaign,
            owner=self.user,
            linkedin_profile=self.profile,
            content="Pending draft",
            linkedin_urn="draft_pending_hidden",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
        )
        ChatMessage.objects.create(
            content_type=lead_ct,
            object_id=other_profile_lead.pk,
            campaign=self.campaign,
            owner=self.user,
            linkedin_profile=other_profile,
            content="Other profile draft",
            linkedin_urn="draft_other_profile_hidden",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
        )
        Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            scheduled_at=timezone.now() - timedelta(hours=1),
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": connected_lead.public_identifier,
                "owner_id": self.user.pk,
                "linkedin_profile_id": self.profile.pk,
            },
        )
        Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            scheduled_at=timezone.now() + timedelta(hours=1),
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": other_profile_lead.public_identifier,
                "owner_id": self.user.pk,
                "linkedin_profile_id": other_profile.pk,
            },
        )
        Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.FAILED,
            scheduled_at=timezone.now(),
            payload={
                "campaign_id": self.campaign.pk,
                "public_id": other_profile_lead.public_identifier,
                "owner_id": self.user.pk,
                "linkedin_profile_id": other_profile.pk,
            },
            error="Other profile failure",
        )
        rf = RequestFactory()

        list_request = rf.get("/api/messages/drafts/")
        list_request.user = self.user
        response = api_message_drafts(list_request)
        payload = json.loads(response.content)
        self.assertEqual([item["id"] for item in payload["items"]], [connected_draft.pk])

        diagnostics_request = rf.get("/api/messages/diagnostics/")
        diagnostics_request.user = self.user
        response = api_messaging_diagnostics(diagnostics_request)
        payload = json.loads(response.content)
        self.assertEqual(payload["diagnostics"]["draftsTotal"], 1)
        self.assertEqual(payload["diagnostics"]["draftsUnapproved"], 1)
        self.assertEqual(payload["diagnostics"]["pendingFollowupTasks"], 0)
        self.assertEqual(payload["diagnostics"]["failedFollowupTasks"], 0)
        self.assertIsNone(payload["diagnostics"]["lastFailedFollowup"])

        approve_request = rf.post(
            "/api/messages/drafts/approve/",
            data=json.dumps({"ids": [connected_draft.pk, pending_draft.pk]}),
            content_type="application/json",
        )
        approve_request.user = self.user
        response = api_message_drafts_approve(approve_request)
        payload = json.loads(response.content)
        self.assertEqual(payload["approved"], 1)
        pending_draft.refresh_from_db()
        self.assertTrue(pending_draft.is_draft)
        self.assertFalse(pending_draft.is_approved)
        self.assertTrue(Task.objects.filter(task_type=Task.TaskType.SEND_MESSAGE, deal=connected_deal).exists())

    def test_follow_up_draft_dedup_is_scoped_to_linkedin_profile_owner(self):
        from django.contrib.auth.models import User
        from django.contrib.contenttypes.models import ContentType
        from linkedin.tasks.follow_up import handle_follow_up
        from chat.models import ChatMessage

        lead = Lead.objects.create(public_identifier="owner_scoped_draft")
        Deal.objects.create(lead=lead, campaign=self.campaign, state=ProfileState.CONNECTED.value)
        other_user = User.objects.create_user(username="other_draft_owner")
        lead_ct = ContentType.objects.get_for_model(Lead)
        ChatMessage.objects.create(
            content_type=lead_ct,
            object_id=lead.pk,
            campaign=self.campaign,
            owner=other_user,
            content="Other account draft",
            linkedin_urn="draft_other_owner",
            is_outgoing=True,
            is_draft=True,
            is_approved=False,
        )
        task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            payload={
                "campaign_id": self.campaign.id,
                "public_id": "owner_scoped_draft",
                "owner_id": self.user.pk,
            },
            scheduled_at=timezone.now(),
        )
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        session.django_user = self.user
        decision = MagicMock(action="send_message", message="Owner-specific draft")

        assessment = MagicMock(state=ProfileState.CONNECTED, source="api_degree_1", confidence=0.95)
        with patch("linkedin.actions.status.get_connection_assessment", return_value=assessment), patch(
            "linkedin.agents.follow_up.run_follow_up_agent",
            return_value=decision,
        ):
            handle_follow_up(task, session, {})

        self.assertTrue(
            ChatMessage.objects.filter(
                content_type=lead_ct,
                object_id=lead.pk,
                campaign=self.campaign,
                owner=self.user,
                is_draft=True,
                content="Owner-specific draft",
            ).exists()
        )
        self.assertEqual(ChatMessage.objects.filter(is_draft=True).count(), 2)
