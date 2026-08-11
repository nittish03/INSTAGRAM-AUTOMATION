# linkedin/actions/connect.py
"""Instagram Follow action."""
from __future__ import annotations

import logging
from typing import Any, Dict

from linkedin.browser.nav import dump_page_html, find_top_card
from linkedin.enums import ProfileState
from linkedin.exceptions import ReachedFollowLimit, SkipProfile

logger = logging.getLogger(__name__)

# TODO: Instagram renames Follow / Following / Requested labels often.
SELECTORS = {
    "follow": [
        'header button:has-text("Follow"):visible',
        'main button:has-text("Follow"):visible',
        'button:has-text("Follow"):visible',
        'div[role="button"]:has-text("Follow"):visible',
    ],
    "following": [
        'header button:has-text("Following"):visible',
        'main button:has-text("Following"):visible',
        'button:has-text("Following"):visible',
    ],
    "requested": [
        'header button:has-text("Requested"):visible',
        'main button:has-text("Requested"):visible',
        'button:has-text("Requested"):visible',
    ],
    "follow_back": [
        'header button:has-text("Follow Back"):visible',
        'main button:has-text("Follow Back"):visible',
        'button:has-text("Follow Back"):visible',
    ],
    "message": [
        'header button:has-text("Message"):visible',
        'main button:has-text("Message"):visible',
        'div[role="button"]:has-text("Message"):visible',
        'a[href*="/direct/t/"]:visible',
    ],
    "action_blocked": [
        'text=/Action Blocked/i',
        'text=/Try Again Later/i',
        'text=/We restrict certain activity/i',
    ],
}


def _first_match(scope, selectors: list[str]):
    for sel in selectors:
        loc = scope.locator(sel)
        if loc.count() > 0:
            return loc.first
    return None


def send_follow_request(session: "AccountSession", profile: Dict[str, Any]) -> ProfileState:
    """Click Follow / Follow Back on an already-loaded Instagram profile page.

    Assumes the profile page is already loaded (caller navigates via
    ``get_follow_status`` or ``visit_profile`` beforehand).
    """
    public_identifier = profile.get("public_identifier")
    page = session.page
    session.wait()

    try:
        header = find_top_card(session)
    except SkipProfile:
        header = page

    if _first_match(page, SELECTORS["following"]) or _first_match(page, SELECTORS["message"]):
        logger.debug("Already following / messageable → %s", public_identifier)
        return ProfileState.CONNECTED

    if _first_match(page, SELECTORS["requested"]):
        logger.debug("Follow already requested → %s", public_identifier)
        return ProfileState.PENDING

    follow_btn = (
        _first_match(header, SELECTORS["follow_back"])
        or _first_match(page, SELECTORS["follow_back"])
        or _first_match(header, SELECTORS["follow"])
        or _first_match(page, SELECTORS["follow"])
    )
    if follow_btn is None:
        logger.debug("Follow button not found for %s — staying QUALIFIED", public_identifier)
        dump_page_html(session, profile, category="follow")
        return ProfileState.QUALIFIED

    follow_btn.click()
    session.wait()
    _check_action_blocked(session)

    if _first_match(page, SELECTORS["requested"]):
        logger.debug("Follow request submitted (private) → %s", public_identifier)
        return ProfileState.PENDING

    if _first_match(page, SELECTORS["following"]) or _first_match(page, SELECTORS["message"]):
        logger.debug("Followed → %s", public_identifier)
        # Public accounts follow immediately; still treat as pending until
        # check_pending confirms they follow back / Message is available for outreach.
        return ProfileState.PENDING

    logger.debug("Follow clicked but state unclear → %s", public_identifier)
    dump_page_html(session, profile, category="follow")
    return ProfileState.PENDING


def _check_action_blocked(session):
    page = session.page
    for sel in SELECTORS["action_blocked"]:
        if page.locator(sel).count() > 0:
            raise ReachedFollowLimit("Instagram action-blocked / rate-limit dialog appeared")


if __name__ == "__main__":
    from linkedin.actions.status import get_follow_status
    from linkedin.browser.registry import cli_parser, cli_session
    from linkedin.url_utils import public_id_to_url

    parser = cli_parser("Follow an Instagram profile")
    parser.add_argument("--profile", required=True, help="Instagram username")
    args = parser.parse_args()
    session = cli_session(args)

    test_profile = {
        "url": public_id_to_url(args.profile),
        "public_identifier": args.profile,
    }
    status = get_follow_status(session, test_profile)
    print(f"Pre-status → {status}")
    result = send_follow_request(session, test_profile)
    print(f"Follow result → {result}")
