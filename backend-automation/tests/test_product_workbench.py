import os

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from crm.models import Deal, Lead
from linkedin.enums import ProfileState
from linkedin.models import Campaign, SiteConfig, Task

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class ProductWorkbenchApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="operator",
            password="testpass123",
            is_staff=True,
        )
        self.client.login(username="operator", password="testpass123")
        self.campaign = Campaign.objects.create(name="Growth")
        self.lead = Lead.objects.create(
            first_name="Ada",
            last_name="Lovelace",
            company_name="Analytical",
            linkedin_url="https://www.linkedin.com/in/adalovelace/",
            public_identifier="adalovelace",
            profile_data={"headline": "Engineer"},
        )
        self.deal = Deal.objects.create(
            lead=self.lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
            reason="Great ICP fit",
        )
        self.failed_task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.FAILED,
            scheduled_at=timezone.now(),
            deal=self.deal,
            payload={"public_id": self.lead.public_identifier, "campaign_id": self.campaign.id},
            error="Rate limit",
        )

    def test_workbench_summary_endpoint(self):
        response = self.client.get("/api/workbench/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("stats", body)
        self.assertIn("inbox", body)

    def test_lead_insights_endpoint(self):
        response = self.client.get(f"/api/leads/{self.lead.id}/insights/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["insights"]
        self.assertEqual(data["leadId"], self.lead.id)
        self.assertIn("qualityScore", data)
        self.assertIn("reasons", data)

    def test_safe_mode_get_and_update(self):
        get_resp = self.client.get("/api/safe-mode/")
        self.assertEqual(get_resp.status_code, 200)
        self.assertTrue(get_resp.json()["settings"]["enabled"])

        patch_resp = self.client.post(
            "/api/safe-mode/",
            data={
                "enabled": True,
                "globalPauseOutreach": True,
                "maxBulkApprove": 3,
                "maxBulkExport": 4,
            },
            content_type="application/json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        cfg = SiteConfig.load()
        self.assertTrue(cfg.global_pause_outreach)
        self.assertEqual(cfg.max_bulk_approve, 3)
        self.assertEqual(cfg.max_bulk_export, 4)

    def test_bulk_retry_blocked_by_safe_mode(self):
        cfg = SiteConfig.load()
        cfg.safe_mode_enabled = True
        cfg.max_bulk_approve = 1
        cfg.save(update_fields=["safe_mode_enabled", "max_bulk_approve"])

        Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            status=Task.Status.FAILED,
            scheduled_at=timezone.now(),
            deal=self.deal,
            payload={},
            error="No profile",
        )

        response = self.client.post(
            "/api/tasks/bulk-retry/",
            data={"ids": [self.failed_task.id, self.failed_task.id + 1]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Safe mode limit exceeded", response.json()["error"])

    def test_safe_mode_post_requires_staff(self):
        non_staff = User.objects.create_user(username="viewer", password="pass123")
        self.client.logout()
        self.client.login(username="viewer", password="pass123")
        response = self.client.post(
            "/api/safe-mode/",
            data={"enabled": False},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_followups_queue_validates_integer_ids(self):
        response = self.client.post(
            "/api/follow-ups/queue/",
            data={"leadIds": ["abc"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
