# linkedin/actions/status.py
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from linkedin.actions.connect import SELECTORS as CONNECT_SELECTORS
from linkedin.actions.search import visit_profile
from linkedin.browser.nav import find_top_card, dump_page_html
from linkedin.enums import ProfileState

logger = logging.getLogger(__name__)

SELECTORS = {
    "pending_button": '[aria-label*="Pending"]',
    "invite_to_connect": CONNECT_SELECTORS["invite_to_connect"],
    "more_button": CONNECT_SELECTORS["more_button"],
    "connect_option": CONNECT_SELECTORS["connect_option"],
}


@dataclass(frozen=True)
class ConnectionAssessment:
    """Inferred connection state + provenance. Not export-grade by itself — see outreach events."""

    state: ProfileState
    source: str
    confidence: float


# ── API layer ──────────────────────────────────────────────────────


def _fetch_degree(session, public_identifier: str, profile: Dict[str, Any]) -> Optional[int]:
    """Return connection degree from API, trying two decorations."""
    from crm.models import Lead
    from linkedin.api.client import PlaywrightLinkedinAPI

    try:
        lead = Lead.objects.get(public_identifier=public_identifier)
    except Lead.DoesNotExist:
        logger.warning("Lead with identifier %s not found in DB — skipping API refresh", public_identifier)
        return profile.get("connection_degree")
    lead.refresh_profile(session, profile_dict=profile)
    degree = profile.get("connection_degree")

    if degree is None:
        api = PlaywrightLinkedinAPI(session=session)
        degree = api.get_connection_degree(public_identifier)
        logger.debug("TopCard degree lookup → %s", degree)

    return degree


# ── UI layer ───────────────────────────────────────────────────────


def _inspect_ui(session, profile: Dict[str, Any]) -> ConnectionAssessment:
    """Determine connection status from profile page buttons (heuristic)."""
    visit_profile(session, profile)
    session.wait()
    top_card = find_top_card(session)

    if top_card.locator(SELECTORS["pending_button"]).count() > 0:
        logger.debug("UI → 'Pending' button detected")
        return ConnectionAssessment(ProfileState.PENDING, "ui_pending", 0.88)

    if top_card.locator(SELECTORS["invite_to_connect"]).count() > 0:
        logger.debug("UI → 'Connect' button detected")
        return ConnectionAssessment(ProfileState.QUALIFIED, "ui_connect_visible", 0.8)

    if _has_connect_in_more(session, top_card):
        logger.debug("UI → 'Connect' in More menu")
        return ConnectionAssessment(ProfileState.QUALIFIED, "ui_more_connect", 0.78)

    if top_card.locator('button[aria-label*="Message"]:visible').count() > 0:
        logger.debug("UI → 'Message' button detected — CONNECTED (heuristic)")
        return ConnectionAssessment(ProfileState.CONNECTED, "ui_message_button", 0.62)

    logger.debug("UI → no connect/pending/message indicators — dumping page")
    dump_page_html(session, profile, category="status")
    try:
        from linkedin.outreach_tracking import raw_log

        raw_log(
            "warning",
            "connection_status",
            f"No clear UI status for {profile.get('public_identifier', '')}",
            payload={"public_id": profile.get("public_identifier")},
        )
    except Exception:
        pass
    return ConnectionAssessment(ProfileState.QUALIFIED, "ui_unknown", 0.25)


def _has_connect_in_more(session, top_card) -> bool:
    more = top_card.locator(SELECTORS["more_button"])
    if more.count() == 0:
        return False
    more.first.click()
    session.wait()
    found = session.page.locator(SELECTORS["connect_option"]).count() > 0
    if not found:
        session.page.keyboard.press("Escape")
    return found


# ── Public entry points ────────────────────────────────────────────


def get_connection_assessment(
    session: "AccountSession",
    profile: Dict[str, Any],
) -> ConnectionAssessment:
    """API-first degree, then UI — always returns source + confidence for inference."""
    public_identifier = profile.get("public_identifier")
    session.ensure_browser()
    logger.debug("Checking connection status → %s", public_identifier)

    degree = _fetch_degree(session, public_identifier, profile)

    if degree == 1:
        logger.debug("API degree 1 → CONNECTED")
        return ConnectionAssessment(ProfileState.CONNECTED, "api_degree_1", 0.95)

    return _inspect_ui(session, profile)


def get_connection_status(
    session: "AccountSession",
    profile: Dict[str, Any],
) -> ProfileState:
    """Backward-compatible: state only (no provenance). Prefer ``get_connection_assessment``."""
    return get_connection_assessment(session, profile).state


if __name__ == "__main__":
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Check LinkedIn connection status")
    parser.add_argument("--profile", required=True, help="Public identifier of the target profile")
    args = parser.parse_args()
    session = cli_session(args)

    test_profile = {
        "url": f"https://www.linkedin.com/in/{args.profile}/",
        "public_identifier": args.profile,
    }

    print(f"Checking connection status as {session} → {args.profile}")
    a = get_connection_assessment(session, test_profile)
    print(f"Connection status → {a.state.value} (source={a.source}, confidence={a.confidence})")
