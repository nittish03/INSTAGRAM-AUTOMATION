# linkedin/actions/status.py
"""Instagram follow-back / messageability assessment (UI-first)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from linkedin.actions.connect import SELECTORS as FOLLOW_SELECTORS
from linkedin.actions.search import visit_profile
from linkedin.browser.nav import dump_page_html, find_top_card
from linkedin.enums import ProfileState

logger = logging.getLogger(__name__)


def _first_match(scope, selectors: list[str]):
    for sel in selectors:
        loc = scope.locator(sel)
        if loc.count() > 0:
            return loc.first
    return None


@dataclass(frozen=True)
class FollowAssessment:
    """Inferred follow/DM state + provenance for export gates."""

    state: ProfileState
    source: str
    confidence: float


def _fetch_relationship(session, public_identifier: str, profile: Dict[str, Any]) -> Optional[dict]:
    """Best-effort relationship flags from Instagram enrichment client."""
    from crm.models import Lead
    from linkedin.api.client import PlaywrightInstagramAPI

    try:
        lead = Lead.objects.get(public_identifier=public_identifier)
    except Lead.DoesNotExist:
        logger.warning("Lead %s not found — skipping API refresh", public_identifier)
        return {
            "follows_viewer": profile.get("follows_viewer"),
            "followed_by_viewer": profile.get("followed_by_viewer"),
        }

    lead.refresh_profile(session, profile_dict=profile)
    rel = {
        "follows_viewer": profile.get("follows_viewer"),
        "followed_by_viewer": profile.get("followed_by_viewer"),
    }
    if rel["follows_viewer"] is None and rel["followed_by_viewer"] is None:
        api = PlaywrightInstagramAPI(session=session)
        rel = api.get_follow_relationship(public_identifier)
    return rel


def _inspect_ui(session, profile: Dict[str, Any]) -> FollowAssessment:
    """Determine follow / DM status from profile page buttons."""
    visit_profile(session, profile)
    session.wait()
    try:
        header = find_top_card(session)
    except Exception:
        header = session.page

    page = session.page

    # Message available → can DM (treat as CONNECTED for outreach pipeline)
    if _first_match(header, FOLLOW_SELECTORS["message"]) or _first_match(page, FOLLOW_SELECTORS["message"]):
        logger.debug("UI → Message button → CONNECTED")
        return FollowAssessment(ProfileState.CONNECTED, "ui_message_button", 0.85)

    # "Follows you" text is a strong follow-back signal
    try:
        if page.get_by_text("Follows you", exact=False).count() > 0:
            logger.debug("UI → Follows you → CONNECTED")
            return FollowAssessment(ProfileState.CONNECTED, "ui_follows_you", 0.9)
    except Exception:
        pass

    if _first_match(page, FOLLOW_SELECTORS["requested"]):
        logger.debug("UI → Requested → PENDING")
        return FollowAssessment(ProfileState.PENDING, "ui_requested", 0.88)

    if _first_match(page, FOLLOW_SELECTORS["following"]):
        # We follow them, but they may not follow back / Message may be restricted
        logger.debug("UI → Following (no Message) → PENDING")
        return FollowAssessment(ProfileState.PENDING, "ui_following_no_message", 0.55)

    if _first_match(page, FOLLOW_SELECTORS["follow"]) or _first_match(page, FOLLOW_SELECTORS["follow_back"]):
        logger.debug("UI → Follow visible → QUALIFIED")
        return FollowAssessment(ProfileState.QUALIFIED, "ui_follow_visible", 0.8)

    logger.debug("UI → unclear status — dumping page")
    dump_page_html(session, profile, category="status")
    try:
        from linkedin.outreach_tracking import raw_log

        raw_log(
            "warning",
            "follow_status",
            f"No clear UI status for {profile.get('public_identifier', '')}",
            payload={"public_id": profile.get("public_identifier")},
        )
    except Exception:
        pass
    return FollowAssessment(ProfileState.QUALIFIED, "ui_unknown", 0.25)


def get_follow_assessment(
    session: "AccountSession",
    profile: Dict[str, Any],
) -> FollowAssessment:
    """API relationship when available, else UI heuristics."""
    public_identifier = profile.get("public_identifier")
    session.ensure_browser()
    logger.debug("Checking Instagram follow status → %s", public_identifier)

    rel = _fetch_relationship(session, public_identifier, profile) or {}
    if rel.get("follows_viewer") is True:
        logger.debug("API follows_viewer → CONNECTED")
        return FollowAssessment(ProfileState.CONNECTED, "api_follows_viewer", 0.92)

    return _inspect_ui(session, profile)


def get_follow_status(
    session: "AccountSession",
    profile: Dict[str, Any],
) -> ProfileState:
    """Backward-compatible: state only."""
    return get_follow_assessment(session, profile).state


if __name__ == "__main__":
    from linkedin.browser.registry import cli_parser, cli_session
    from linkedin.url_utils import public_id_to_url

    parser = cli_parser("Check Instagram follow status")
    parser.add_argument("--profile", required=True, help="Instagram username")
    args = parser.parse_args()
    session = cli_session(args)

    test_profile = {
        "url": public_id_to_url(args.profile),
        "public_identifier": args.profile,
    }
    a = get_follow_assessment(session, test_profile)
    print(f"Status → {a.state.value} (source={a.source}, confidence={a.confidence})")
