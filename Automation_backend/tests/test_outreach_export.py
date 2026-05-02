"""Tests for verification-gated sheet export and outreach events."""

import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from crm.models import Deal, Lead
from google_integration.models import GoogleAccount
from google_integration.sheet_sync import (
    build_sheet_row,
    derive_active_label,
    normalize_sheet_status,
    sync_lead_to_google_sheet,
)
from linkedin.enums import ProfileState
from linkedin.models import Campaign, OutreachEvent, SiteConfig
from linkedin.outreach_tracking import emit_outreach_event, lead_sheet_export_verification

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class OutreachExportGateTests(TestCase):
    def setUp(self):
        self.cfg = SiteConfig.load()
        self.cfg.google_sheet_sync_enabled = False
        self.cfg.save()

        self.user = User.objects.create_user("syncuser", password="x", is_superuser=True)
        self.campaign = Campaign.objects.create(name="TestCamp")
        self.lead = Lead.objects.create(
            first_name="A",
            last_name="B",
            company_name="Co",
            linkedin_url="https://www.linkedin.com/in/ab/",
            public_identifier="ab",
            profile_data={"headline": "Dev"},
        )
        self.deal = Deal.objects.create(
            lead=self.lead,
            campaign=self.campaign,
            state=ProfileState.CONNECTED.value,
        )

    def test_no_event_not_eligible(self):
        ok, reason, _ = lead_sheet_export_verification(self.lead)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_connection_detected_event")

    def test_api_degree_event_eligible_without_invite(self):
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )
        ok, reason, label = lead_sheet_export_verification(self.lead)
        self.assertTrue(ok)
        self.assertEqual(reason, "verified_api_first_degree")
        row = build_sheet_row(self.lead, status_label=label, verification_reason=reason)
        self.assertEqual(len(row), 10)
        self.assertEqual(row[5], "Connected")
        self.assertEqual(row[6], derive_active_label("Connected"))
        self.assertRegex(row[8], r"^\d{2}/\d{2}/\d{4}$")
        self.assertEqual(row[9], "")

    def test_normalize_and_active_are_deterministic(self):
        self.assertEqual(normalize_sheet_status("Verified (API)"), "Connected")
        self.assertEqual(normalize_sheet_status("Accepted (post-invite)"), "Connected")
        self.assertEqual(normalize_sheet_status("Pending"), "Pending")
        self.assertEqual(derive_active_label("Qualified"), "Follow up")
        self.assertEqual(derive_active_label("Pending"), "Follow up-1")
        self.assertEqual(derive_active_label("Connected"), "Follow up-2")

    def test_ui_only_without_invite_not_eligible(self):
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "ui_message_button", "confidence": 0.62},
        )
        ok, reason, _ = lead_sheet_export_verification(self.lead)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_invite_for_non_api_path")

    def test_ui_after_invite_eligible(self):
        emit_outreach_event(
            OutreachEvent.EventType.INVITE_SENT,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={},
        )
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "ui_message_button", "confidence": 0.62},
        )
        ok, reason, _ = lead_sheet_export_verification(self.lead)
        self.assertTrue(ok)
        self.assertEqual(reason, "verified_after_invite")

    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_sync_skips_without_verification_when_enabled(
        self, mock_resolve, mock_get_values, mock_update
    ):
        GoogleAccount.objects.create(
            user=self.user,
            refresh_token="not-empty",
            google_email="a@b.com",
        )
        self.cfg.google_sheet_sync_enabled = True
        self.cfg.google_sheet_id = "test_sheet_id"
        self.cfg.google_sheet_sync_user = self.user
        self.cfg.save()

        mock_resolve.return_value = self.user
        mock_get_values.return_value = []

        self.assertFalse(sync_lead_to_google_sheet(self.lead))
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )
        self.assertTrue(sync_lead_to_google_sheet(self.lead))
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.sheet_exported_at)
