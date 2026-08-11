#!/usr/bin/env python
"""
Bootstrap script for initial CRM data.

Ensures a default Instagram outreach campaign exists with Eshway website-dev
+ agency-collaboration product docs / objective when the DB is empty.
Idempotent — safe to run multiple times.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CAMPAIGN_NAME = "Instagram Outreach — Web Dev & Collab"

_DEFAULTS_DIR = Path(__file__).resolve().parents[2] / "defaults"
_PRODUCT_DOCS_FILE = _DEFAULTS_DIR / "eshway_product_docs.md"
_OBJECTIVE_FILE = _DEFAULTS_DIR / "eshway_campaign_objective.md"

DEFAULT_SEARCH_KEYWORDS = [
    # CLIENT — website development
    "founder website",
    "local business owner",
    "coach consultant",
    "ecommerce brand",
    "startup founder",
    "service business",
    # COLLABORATION — agencies / creatives
    "branding agency",
    "graphic designer",
    "marketing agency",
    "ui ux designer",
    "social media agency",
    "creative studio",
]


def _read_default(path: Path, fallback: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or fallback
    except OSError:
        return fallback


def setup_crm():
    """Create default campaign + seed search keywords if none exist."""
    from linkedin.models import Campaign, SearchKeyword

    product_docs = _read_default(
        _PRODUCT_DOCS_FILE,
        "Eshway builds websites and digital solutions for businesses, "
        "and partners with agencies/creatives on development.",
    )
    objective = _read_default(
        _OBJECTIVE_FILE,
        "Find Instagram CLIENTS needing websites and COLLABORATION partners "
        "(agencies/creatives) for development work.",
    )

    campaign = Campaign.objects.filter(name=DEFAULT_CAMPAIGN_NAME).first()
    if campaign is None and not Campaign.objects.exists():
        campaign = Campaign.objects.create(
            name=DEFAULT_CAMPAIGN_NAME,
            product_docs=product_docs,
            campaign_objective=objective,
        )
        logger.info("Created default campaign: %s", DEFAULT_CAMPAIGN_NAME)
    elif campaign is None:
        campaign = Campaign.objects.order_by("pk").first()
        # Backfill empty docs/objective on the oldest campaign only when blank.
        updates = []
        if campaign and not (campaign.product_docs or "").strip():
            campaign.product_docs = product_docs
            updates.append("product_docs")
        if campaign and not (campaign.campaign_objective or "").strip():
            campaign.campaign_objective = objective
            updates.append("campaign_objective")
        if campaign and updates:
            campaign.save(update_fields=updates)
            logger.info("Backfilled campaign %s fields: %s", campaign.name, updates)

    if campaign is not None:
        existing = set(
            SearchKeyword.objects.filter(campaign=campaign).values_list("keyword", flat=True)
        )
        created = 0
        for kw in DEFAULT_SEARCH_KEYWORDS:
            if kw in existing:
                continue
            SearchKeyword.objects.create(campaign=campaign, keyword=kw)
            created += 1
        if created:
            logger.info("Seeded %d default Instagram search keywords", created)

    logger.debug("CRM setup complete.")
