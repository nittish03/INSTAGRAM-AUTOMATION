import os
from unittest.mock import MagicMock, patch

import numpy as np
from django.test import TestCase

from crm.models import ClosingReason, Deal, Lead
from linkedin.enums import ProfileState
from linkedin.models import Campaign
from linkedin.pipeline.pools import qualify_source
from linkedin.pipeline.qualify import run_qualification

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


class QualificationPipelineTest(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(
            name="Qualification Campaign",
            product_docs="Product docs",
            campaign_objective="Find strong prospects",
        )
        self.session = MagicMock()
        self.session.campaign = self.campaign

    def _create_embedded_lead(self, public_id: str) -> Lead:
        embedding = np.ones(384, dtype=np.float32).tobytes()
        return Lead.objects.create(
            first_name="Test",
            last_name="Lead",
            instagram_url=f"https://www.instagram.com/{public_id}/",
            public_identifier=public_id,
            embedding=embedding,
        )

    def _qualifier(self):
        qualifier = MagicMock()
        qualifier.n_obs = 0
        qualifier.class_counts = (0, 0)
        qualifier.predict.return_value = None
        qualifier.acquisition_scores.return_value = None
        return qualifier

    @patch("linkedin.pipeline.qualify._fetch_profile_text", return_value="profile text")
    @patch("linkedin.ml.qualifier.qualify_with_llm", return_value=(0, "Not a fit"))
    def test_rejected_lead_is_not_returned_for_connection(self, _mock_llm, _mock_profile_text):
        lead = self._create_embedded_lead("bad-fit")

        result = run_qualification(self.session, self._qualifier())

        self.assertIsNone(result)
        deal = Deal.objects.get(lead=lead, campaign=self.campaign)
        self.assertEqual(deal.state, ProfileState.FAILED)
        self.assertEqual(deal.closing_reason, ClosingReason.DISQUALIFIED)

    @patch("linkedin.pipeline.qualify._fetch_profile_text", return_value="profile text")
    @patch("linkedin.ml.qualifier.qualify_with_llm", return_value=(1, "Good fit"))
    def test_accepted_lead_is_returned_for_connection(self, _mock_llm, _mock_profile_text):
        lead = self._create_embedded_lead("good-fit")

        result = run_qualification(self.session, self._qualifier())

        self.assertEqual(result, "good-fit")
        deal = Deal.objects.get(lead=lead, campaign=self.campaign)
        self.assertEqual(deal.state, ProfileState.QUALIFIED)

    @patch("linkedin.pipeline.qualify._fetch_profile_text", return_value="profile text")
    @patch("linkedin.ml.qualifier.qualify_with_llm")
    def test_qualify_source_skips_rejections_until_accepted(self, mock_llm, _mock_profile_text):
        rejected = self._create_embedded_lead("bad-fit")
        accepted = self._create_embedded_lead("good-fit")
        mock_llm.side_effect = [(0, "Not a fit"), (1, "Good fit")]

        result = next(qualify_source(self.session, self._qualifier()), None)

        self.assertEqual(result, "good-fit")
        rejected_deal = Deal.objects.get(lead=rejected, campaign=self.campaign)
        accepted_deal = Deal.objects.get(lead=accepted, campaign=self.campaign)
        self.assertEqual(rejected_deal.state, ProfileState.FAILED)
        self.assertEqual(accepted_deal.state, ProfileState.QUALIFIED)

    @patch("linkedin.db.leads.promote_lead_to_deal", side_effect=ValueError("No Lead"))
    @patch("linkedin.pipeline.qualify._fetch_profile_text", return_value="profile text")
    @patch("linkedin.ml.qualifier.qualify_with_llm", return_value=(1, "Good fit"))
    def test_promotion_failure_is_not_returned_for_connection(
        self,
        _mock_llm,
        _mock_profile_text,
        _mock_promote,
    ):
        lead = self._create_embedded_lead("promotion-failed")

        result = run_qualification(self.session, self._qualifier())

        self.assertIsNone(result)
        deal = Deal.objects.get(lead=lead, campaign=self.campaign)
        self.assertEqual(deal.state, ProfileState.FAILED)
        self.assertEqual(deal.closing_reason, ClosingReason.DISQUALIFIED)
