"""Tests for verification-gated sheet export and outreach events."""

import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from crm.models import Deal, Lead
from google_integration.models import GoogleAccount
from google_integration.sheet_sync import (
    SHEET_HEADER,
    build_sheet_row,
    derive_active_label,
    normalize_sheet_status,
    sync_lead_to_google_sheet,
    sync_pending_lead_to_google_sheet,
    sync_qualified_lead_to_google_sheet,
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
        self.assertEqual(row[4], "TRUE")
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
        self.lead.first_name = "=HYPERLINK"
        row = build_sheet_row(self.lead, status_label="Pending")
        self.assertEqual(row[0], "'=HYPERLINK B")

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

    def test_ui_after_invite_not_export_grade(self):
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
        self.assertFalse(ok)
        self.assertEqual(reason, "insufficient_confidence_or_source")

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_sync_skips_without_verification_when_enabled(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A2:J2")
        self.assertFalse(mock_append.called)
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.sheet_exported_at)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_verified_connected_sync_allows_missing_profile_data(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        self.lead.profile_data = None
        self.lead.save(update_fields=["profile_data"])
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )

        mock_resolve.return_value = self.user
        mock_get_values.return_value = []

        self.assertTrue(sync_lead_to_google_sheet(self.lead))
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[0], "A B")
        self.assertEqual(written_row[1], "Co")
        self.assertEqual(written_row[5], "Connected")
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_pending_invite_sync_writes_pending_row(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        self.deal.state = ProfileState.PENDING.value
        self.deal.save(update_fields=["state"])

        mock_resolve.return_value = self.user
        mock_get_values.return_value = []

        self.assertTrue(sync_pending_lead_to_google_sheet(self.lead, reason_code="invite_sent"))
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A2:J2")
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[4], "FALSE")
        self.assertEqual(written_row[5], "Pending")
        self.assertEqual(written_row[6], "Follow up-1")
        self.assertFalse(mock_append.called)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.sheet_exported_at)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_connected_sync_updates_existing_pending_row(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [
            [SHEET_HEADER],
            [
                SHEET_HEADER,
                ["A B", "Co", "Dev", self.lead.linkedin_url, "TRUE", "Pending", "Follow up-1"],
            ],
        ]

        self.assertTrue(sync_lead_to_google_sheet(self.lead))
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A2:J2")
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[5], "Connected")
        self.assertEqual(written_row[6], "Follow up-2")
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_existing_row_update_preserves_review_column(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [
            [SHEET_HEADER],
            [
                SHEET_HEADER,
                ["A B", "Co", "Dev", self.lead.linkedin_url, "TRUE", "Pending", "Follow up-1", "Needs review"],
            ],
        ]

        self.assertTrue(sync_lead_to_google_sheet(self.lead))
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[7], "Needs review")
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_pending_sync_repairs_missing_row_even_when_marked_exported(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        self.deal.state = ProfileState.PENDING.value
        self.deal.save(update_fields=["state"])
        self.lead.sheet_exported_at = timezone.now()
        self.lead.save(update_fields=["sheet_exported_at"])

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [[SHEET_HEADER], [SHEET_HEADER], [SHEET_HEADER]]

        self.assertTrue(sync_pending_lead_to_google_sheet(self.lead, reason_code="check_pending_ui_pending"))
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A2:J2")
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[5], "Pending")
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_pending_sync_overwrites_stale_connected_sheet_row(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        self.deal.state = ProfileState.PENDING.value
        self.deal.save(update_fields=["state"])
        self.lead.sheet_exported_at = timezone.now()
        self.lead.save(update_fields=["sheet_exported_at"])

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [
            [SHEET_HEADER],
            [
                SHEET_HEADER,
                ["A B", "Co", "Dev", self.lead.linkedin_url, "TRUE", "Connected", "Follow up-2"],
            ],
        ]

        self.assertTrue(sync_pending_lead_to_google_sheet(self.lead, reason_code="downgrade_pending"))
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A2:J2")
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[5], "Pending")
        self.assertEqual(written_row[6], "Follow up-1")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.sheet_exported_at)
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_qualified_sync_overwrites_stale_connected_sheet_row(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        self.deal.state = ProfileState.QUALIFIED.value
        self.deal.save(update_fields=["state"])
        self.lead.sheet_exported_at = timezone.now()
        self.lead.save(update_fields=["sheet_exported_at"])

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [
            [SHEET_HEADER],
            [
                SHEET_HEADER,
                ["A B", "Co", "Dev", self.lead.linkedin_url, "TRUE", "Connected", "Follow up-2"],
            ],
        ]

        self.assertTrue(sync_qualified_lead_to_google_sheet(self.lead, reason_code="downgrade_qualified"))
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[5], "Qualified")
        self.assertEqual(written_row[6], "Follow up")
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.sheet_exported_at)
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_connected_signal_sync_runs_even_after_pending_export_marker(
        self, mock_resolve, mock_get_values, mock_update, mock_append
    ):
        from crm.signals import _sync_lead_after_commit

        GoogleAccount.objects.create(
            user=self.user,
            refresh_token="not-empty",
            google_email="a@b.com",
        )
        self.cfg.google_sheet_sync_enabled = True
        self.cfg.google_sheet_id = "test_sheet_id"
        self.cfg.google_sheet_sync_user = self.user
        self.cfg.save()
        self.lead.sheet_exported_at = timezone.now()
        self.lead.save(update_fields=["sheet_exported_at"])
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [
            [SHEET_HEADER],
            [
                SHEET_HEADER,
                ["A B", "Co", "Dev", self.lead.linkedin_url, "TRUE", "Pending", "Follow up-1"],
            ],
        ]

        _sync_lead_after_commit(self.lead.pk)

        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A2:J2")
        written_row = mock_update.call_args.args[3][0]
        self.assertEqual(written_row[5], "Connected")
        self.assertEqual(written_row[6], "Follow up-2")
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_sheet_row_match_uses_linkedin_column_not_substring(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )

        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [
            [SHEET_HEADER],
            [
                SHEET_HEADER,
                ["AB Adjacent", "Co", "Dev", "https://www.linkedin.com/in/not-ab/", "TRUE", "Pending"],
            ],
            [["Name"], ["AB Adjacent"]],
        ]

        self.assertTrue(sync_lead_to_google_sheet(self.lead))
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A3:J3")
        self.assertFalse(mock_append.called)

    @patch("google_integration.sheet_sync.append_rows")
    @patch("google_integration.sheet_sync.update_values")
    @patch("google_integration.sheet_sync.get_values")
    @patch("google_integration.sheet_sync.resolve_google_sync_user")
    def test_new_row_sync_fills_first_empty_gap_before_later_rows(
        self, mock_resolve, mock_get_values, mock_update, mock_append
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
        emit_outreach_event(
            OutreachEvent.EventType.CONNECTION_DETECTED,
            lead=self.lead,
            deal=self.deal,
            campaign=self.campaign,
            metadata={"source": "api_degree_1", "confidence": 0.95},
        )

        rows_with_gap = [
            SHEET_HEADER,
            ["Existing", "Co", "Dev", "https://www.linkedin.com/in/existing/", "TRUE", "Connected"],
            [],
            ["Later", "Co", "Dev", "https://www.linkedin.com/in/later/", "TRUE", "Connected"],
        ]
        mock_resolve.return_value = self.user
        mock_get_values.side_effect = [[SHEET_HEADER], rows_with_gap, rows_with_gap]

        self.assertTrue(sync_lead_to_google_sheet(self.lead))
        self.assertEqual(mock_update.call_args.args[2], "Sheet1!A3:J3")
        self.assertFalse(mock_append.called)
