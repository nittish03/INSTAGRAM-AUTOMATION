# linkedin/actions/message.py
"""Send Instagram DMs via Playwright UI (HITL-approved text only at call site)."""
from __future__ import annotations

import logging
from typing import Any, Dict

from playwright.sync_api import Error as PlaywrightError

from linkedin.browser.nav import dump_page_html, goto_page, human_type
from linkedin.exceptions import TaskSkipped
from linkedin.url_utils import public_id_to_url

logger = logging.getLogger(__name__)

INSTAGRAM_INBOX_URL = "https://www.instagram.com/direct/inbox/"

# TODO: Instagram DM composer selectors drift often.
SELECTOR_CHAINS = {
    "message_button": [
        'header button:has-text("Message"):visible',
        'main button:has-text("Message"):visible',
        'div[role="button"]:has-text("Message"):visible',
        'a[href*="/direct/t/"]:visible',
    ],
    "message_input": [
        'div[role="textbox"][contenteditable="true"]:visible',
        'textarea[placeholder*="Message" i]:visible',
        'div[aria-label*="Message" i][contenteditable="true"]:visible',
        'div[contenteditable="true"]:visible',
    ],
    "send_button": [
        'button:has-text("Send"):visible',
        'div[role="button"]:has-text("Send"):visible',
    ],
}


def _find(page, key: str, timeout: int = 5000):
    chain = SELECTOR_CHAINS[key]
    for sel in chain:
        loc = page.locator(sel)
        try:
            loc.first.wait_for(state="visible", timeout=timeout)
            return loc.first
        except (PlaywrightError, TimeoutError):
            continue
    raise PlaywrightError(f"No selector matched for '{key}'. Tried: {', '.join(chain)}")


def _ensure_messageable(session) -> None:
    page = session.page
    for sel in SELECTOR_CHAINS["message_button"]:
        if page.locator(sel).count() > 0:
            return
    raise TaskSkipped(
        "Instagram Message button not available (private/restricted or Message UI missing)"
    )


def _open_dm_thread(session) -> None:
    page = session.page
    btn = _find(page, "message_button", timeout=8000)
    btn.click()
    session.wait()
    # Wait for composer
    _find(page, "message_input", timeout=15000)


def _type_and_send(session, message: str) -> bool:
    page = session.page
    input_area = _find(page, "message_input", timeout=10000)
    input_area.click()
    try:
        input_area.fill("")
    except Exception:
        pass
    human_type(input_area, message)
    session.wait(1, 2)

    # Prefer Send button; fallback Enter
    sent = False
    for sel in SELECTOR_CHAINS["send_button"]:
        loc = page.locator(sel)
        if loc.count() > 0:
            loc.first.click()
            sent = True
            break
    if not sent:
        page.keyboard.press("Enter")

    session.wait(2, 4)
    # Soft verify: input mostly cleared
    try:
        remaining = (input_area.inner_text() or "").strip()
        if remaining and remaining == message.strip():
            logger.warning("DM composer still contains full message after send")
            return False
    except Exception:
        pass
    return True


def send_raw_message(session, profile: Dict[str, Any], message: str) -> bool:
    """Send an arbitrary Instagram DM. Returns True if sent."""
    from linkedin.actions.search import _go_to_profile

    public_identifier = (profile.get("public_identifier") or "").lstrip("@")
    if not public_identifier or not (message or "").strip():
        return False

    session.ensure_browser()
    _go_to_profile(session, public_id_to_url(public_identifier), public_identifier)
    session.wait()

    try:
        _ensure_messageable(session)
        _open_dm_thread(session)
        if _type_and_send(session, message.strip()):
            logger.info("Instagram DM sent to %s", public_identifier)
            return True
        dump_page_html(session, profile, category="message")
        return False
    except TaskSkipped:
        raise
    except (PlaywrightError, TimeoutError, RuntimeError) as exc:
        logger.error("Failed to send Instagram DM to %s → %s", public_identifier, exc)
        dump_page_html(session, profile, category="message")
        return False


def open_inbox(session) -> None:
    session.ensure_browser()
    goto_page(
        session,
        action=lambda: session.page.goto(INSTAGRAM_INBOX_URL),
        expected_url_pattern="/direct/",
        error_message="Failed to open Instagram DM inbox",
    )
