# linkedin/actions/message.py
import json
import logging
import time
from typing import Dict, Any

from playwright.sync_api import Error as PlaywrightError, Locator
from linkedin.actions.connect import SELECTORS as CONNECT_SELECTORS
from linkedin.browser.nav import goto_page, human_type, dump_page_html, find_top_card
from linkedin.exceptions import TaskSkipped

logger = logging.getLogger(__name__)

LINKEDIN_MESSAGING_URL = "https://www.linkedin.com/messaging/"

# Selector fallback chains: semantic/ARIA first, then class-based.
# LinkedIn A/B tests UI variants per account and renames classes often.
# Each key maps to a list tried in order; first with a match wins.
SELECTOR_CHAINS = {
    # ── Profile page ──
    "message_button": [
        'button[aria-label*="Message"]:visible',
        'button:has-text("Message"):visible',
    ],
    "overflow_action": [
        'button[id$="profile-overflow-action"]:visible',
        'button[aria-label="More actions"]:visible',
        'main section button:has-text("More"):visible',
    ],
    "message_option": [
        'div[role="menu"] a[href*="/messaging/"]:visible',
        'div[role="menuitem"]:has-text("Message"):visible',
        'div[aria-label$="to message"]:visible',
        'li:has-text("Message"):visible',
    ],
    # ── Popup / thread compose ──
    "message_input": [
        'div[role="textbox"][aria-label*="Write a message"]:visible',
        'div[role="textbox"][aria-label*="message"i]:visible',
        'div[class*="msg-form__contenteditable"]:visible',
        'div[contenteditable="true"]:visible',
    ],
    "send_button": [
        'button[aria-label="Send"]:visible',
        'button.msg-form__send-button:visible',
        'button[type="submit"][class*="msg-form"]:visible',
        'form button[type="submit"]:visible',
        'button[type="submit"]:visible',
    ],
    # ── Messaging inbox compose ──
    "new_message_button": [
        'button.msg-conversations-container__compose-btn:visible',
        'button[aria-label*="Compose"]:visible',
        'button[aria-label*="New message"]:visible',
        'button:has(svg[data-test-icon="compose-medium"]):visible',
    ],
    # ── New thread: recipient search ──
    "connections_input": [
        'input[role="combobox"][placeholder*="name"]',
        'input[class*="msg-connections"]',
        'input[placeholder*="Type a name"]',
        'input[type="text"][aria-owns]',
    ],
    "search_result_row": [
        'ul[role="listbox"] li[role="option"]',
        'div[class*="msg-connections-typeahead__search-result-row"]',
        'li[class*="search-result"]',
    ],
    # ── Thread: compose area ──
    "compose_input": [
        'div[role="textbox"][aria-label*="Write a message"]',
        'div[role="textbox"][aria-label*="message"i]',
        'div[class*="msg-form__contenteditable"]',
        'div[contenteditable="true"]',
    ],
    "compose_send": [
        'button[type="submit"][class*="msg-form"]',
        'button[class*="send-btn"]',
        'button[class*="send-button"]',
        'form button[type="submit"]',
        'button[type="submit"]',
    ],
}


def _find(page, key: str, timeout: int = 5000) -> Locator:
    """Try each selector in the chain for *key*, return the first with matches.

    Raises PlaywrightError if none match within *timeout* ms.
    """
    chain = SELECTOR_CHAINS[key]
    for sel in chain:
        loc = page.locator(sel)
        try:
            loc.first.wait_for(state="attached", timeout=timeout)
            logger.debug("Selector hit for %s: %s", key, sel)
            return loc
        except (PlaywrightError, TimeoutError):
            continue
    tried = ", ".join(chain)
    raise PlaywrightError(f"No selector matched for '{key}'. Tried: {tried}")


def _open_compose_popup(session, page) -> bool:
    """Open the messaging compose popup on the current profile page.

    Tries the direct Message button first, then More → Message.
    Returns True if the popup was opened.
    """
    try:
        direct = _find(page, "message_button", timeout=3000)
        direct.first.click()
        logger.debug("Opened compose popup (direct button)")
        return True
    except PlaywrightError:
        pass

    try:
        _find(page, "overflow_action").first.click()
        session.wait()
        _find(page, "message_option").first.click()
        logger.debug("Opened compose popup (More → Message)")
        return True
    except PlaywrightError:
        return False


def _ensure_profile_is_messageable(session) -> None:
    """Skip sending when LinkedIn still shows this profile is not messageable."""
    try:
        top_card = find_top_card(session)
    except Exception as exc:
        raise TaskSkipped(f"Cannot verify profile messageability: {exc}") from exc

    pending = top_card.locator('[aria-label*="Pending"]:visible')
    if pending.count() > 0:
        raise TaskSkipped("LinkedIn still shows Pending; skipping message send")

    connect = top_card.locator(CONNECT_SELECTORS["invite_to_connect"])
    if connect.count() > 0:
        raise TaskSkipped("LinkedIn still shows Connect; skipping message send")

    more = top_card.locator(CONNECT_SELECTORS["more_button"])
    if more.count() > 0:
        try:
            more.first.click(timeout=5_000)
            session.wait()
            connect_option = session.page.locator(CONNECT_SELECTORS["connect_option"])
            if connect_option.count() > 0:
                raise TaskSkipped("LinkedIn still shows Connect in More menu; skipping message send")
            session.page.keyboard.press("Escape")
        except TaskSkipped:
            raise
        except Exception as exc:
            logger.debug("Could not inspect More menu before message send: %s", exc)


def _type_message(session, page, message: str, input_area: Locator | None = None) -> Locator:
    """Type a message into the compose popup input area."""
    input_area = input_area or _find(page, "message_input").first
    try:
        input_area.focus(timeout=5000)
        input_area.press("ControlOrMeta+A")
        input_area.press("Backspace")
        human_type(input_area, message, min_delay=5, max_delay=20)
        logger.debug("Message typed with keyboard events")
    except Exception:
        logger.debug("keyboard typing failed → using clipboard paste")
        input_area.focus(timeout=5000)
        page.evaluate(f"() => navigator.clipboard.writeText({json.dumps(message)})")
        session.wait()
        page.keyboard.press("ControlOrMeta+V")
        session.wait()
    return input_area


def _find_scoped_send_button(page, input_area: Locator, timeout: int = 5000) -> Locator:
    """Find the Send button for the same LinkedIn compose form as input_area."""
    scopes = [
        input_area.locator("xpath=ancestor::form[1]"),
        input_area.locator("xpath=ancestor::*[contains(@class, 'msg-form')][1]"),
    ]
    for scope in scopes:
        try:
            scope.first.wait_for(state="attached", timeout=1000)
        except (PlaywrightError, TimeoutError):
            continue
        for sel in SELECTOR_CHAINS["send_button"]:
            loc = scope.locator(sel)
            try:
                loc.first.wait_for(state="attached", timeout=timeout)
                logger.debug("Selector hit for scoped send_button: %s", sel)
                return loc.first
            except (PlaywrightError, TimeoutError):
                continue

    logger.debug("No scoped send button found; falling back to page-level send button")
    return _find(page, "send_button", timeout=timeout).first


def _log_disabled_send_diagnostics(send_btn: Locator, input_area: Locator) -> None:
    try:
        button_html = send_btn.evaluate("el => el.outerHTML")
    except Exception as exc:
        button_html = f"<unavailable: {exc}>"
    try:
        input_text = input_area.inner_text(timeout=1000).strip()
    except Exception as exc:
        input_text = f"<unavailable: {exc}>"
    logger.error(
        "Send button stayed disabled → send failed (input_len=%s, button=%s)",
        len(input_text),
        button_html[:500],
    )


def _click_send_and_verify(session, page, input_area: Locator) -> bool:
    """Click the send button and verify the message was actually sent.

    After clicking send, the input should clear. If text remains,
    the send failed silently.
    """
    for attempt in range(2):
        send_btn = _find_scoped_send_button(page, input_area)
        deadline = time.monotonic() + 10
        while not send_btn.is_enabled(timeout=1000):
            if time.monotonic() >= deadline:
                _log_disabled_send_diagnostics(send_btn, input_area)
                return False
            session.wait(0.5, 1)
        send_btn.scroll_into_view_if_needed(timeout=2000)
        send_btn.click(delay=200)
        session.wait(4, 5)

        try:
            text = input_area.inner_text(timeout=2000).strip()
            if not text:
                return True
            if attempt == 0:
                logger.warning("Message input still has text after send click → retrying send")
                continue
            logger.error("Message input still has text after send retry → send failed")
            return False
        except (PlaywrightError, TimeoutError):
            pass  # input gone → popup closed → success
            return True

    return True


def _discard_compose_draft(page) -> None:
    """Clear any text typed into LinkedIn so failed sends do not remain as drafts."""
    try:
        input_area = _find(page, "message_input", timeout=2000).first
        input_area.focus(timeout=2000)
        input_area.press("ControlOrMeta+A")
        input_area.press("Backspace")
        logger.debug("Cleared LinkedIn compose text after failed send")
    except Exception as exc:
        logger.debug("Could not clear LinkedIn compose text: %s", exc)

    try:
        page.keyboard.press("Escape")
    except Exception as exc:
        logger.debug("Could not close LinkedIn compose popup: %s", exc)


# ── Public entry point ────────────────────────────────────────────


def send_raw_message(session, profile: Dict[str, Any], message: str) -> bool:
    """Send an arbitrary message to a profile. Returns True if sent."""
    from linkedin.actions.search import _go_to_profile
    from linkedin.url_utils import public_id_to_url

    public_identifier = profile.get("public_identifier")

    _go_to_profile(session, public_id_to_url(public_identifier), public_identifier)
    if _send_msg_pop_up(session, profile, message):
        return True
    dump_page_html(session, profile, category="message_popup")

    logger.error("Profile UI send failed for %s", public_identifier)
    return False


# ── Send strategies ───────────────────────────────────────────────


def _send_msg_pop_up(session, profile: Dict[str, Any], message: str) -> bool:
    """Open compose popup on the profile page, type, send, verify."""
    session.wait()
    page = session.page
    public_identifier = profile.get("public_identifier")

    try:
        _ensure_profile_is_messageable(session)

        if not _open_compose_popup(session, page):
            return False

        session.wait()
        input_area = _type_message(session, page, message)

        if not _click_send_and_verify(session, page, input_area):
            _discard_compose_draft(page)
            session.wait()
            return False

        page.keyboard.press("Escape")
        session.wait()

        logger.info("Message sent to %s", public_identifier)
        return True

    except (PlaywrightError, TimeoutError) as e:
        logger.error("Failed to send message to %s → %s", public_identifier, e)
        _discard_compose_draft(page)
        return False


def _send_message(session, profile: Dict[str, Any], message: str) -> bool:
    """Use LinkedIn Messaging's normal compose flow: New message → recipient → Send."""
    public_identifier = profile.get("public_identifier")
    full_name = profile.get("full_name") or \
        f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    if not full_name:
        logger.error("Cannot send via direct thread: no full_name for %s", public_identifier)
        return False
    try:
        goto_page(
            session,
            action=lambda: session.page.goto(LINKEDIN_MESSAGING_URL),
            expected_url_pattern="/messaging",
            timeout=30_000,
            error_message="Error opening messaging",
        )

        _find(session.page, "new_message_button").first.click(delay=200)
        session.wait(1, 2)

        conn_input = _find(session.page, "connections_input").first
        conn_input.fill("")
        session.wait(0.5, 1)

        human_type(conn_input, full_name, min_delay=10, max_delay=50)
        session.wait(2, 3)

        rows = _find(session.page, "search_result_row")
        item = None
        name_in_result = ""
        for i in range(min(rows.count(), 5)):
            row = rows.nth(i)
            row_text = row.inner_text(timeout=5_000)
            row_name = row_text.split("•")[0].split("\n")[0].strip()
            if row_name.lower() == full_name.lower() or full_name.lower() in row_text.lower():
                item = row
                name_in_result = row_name or row_text.strip()
                break
        if item is None:
            logger.error(
                "Recipient not found in messaging compose for %s: expected '%s'",
                public_identifier, full_name,
            )
            return False

        item.scroll_into_view_if_needed()
        item.click(delay=200)
        session.wait(1, 2)
        logger.debug("Selected messaging recipient for %s → %s", public_identifier, name_in_result)

        input_area = _find(session.page, "compose_input").first
        input_area = _type_message(session, session.page, message, input_area=input_area)

        if not _click_send_and_verify(session, session.page, input_area):
            _discard_compose_draft(session.page)
            return False

        logger.info("Message sent to %s (messaging compose)", public_identifier)
        return True
    except (PlaywrightError, TimeoutError) as e:
        logger.error("Failed to send message to %s (direct thread) → %s", public_identifier, e)
        return False


def _send_message_via_api(session, profile: Dict[str, Any], message: str) -> bool:
    """Last-resort fallback: send via Voyager Messaging API.

    Requires profile dict to contain 'urn' (target profile URN).
    """
    from linkedin.api.client import PlaywrightLinkedinAPI
    from linkedin.api.messaging import send_message
    from linkedin.actions.conversations import find_conversation_urn, find_conversation_urn_via_navigation

    public_identifier = profile.get("public_identifier")
    target_urn = profile.get("urn")
    if not target_urn:
        logger.error("API send failed for %s → no URN in profile dict", public_identifier)
        return False

    mailbox_urn = session.self_profile["urn"]
    api = PlaywrightLinkedinAPI(session=session)

    conversation_urn = find_conversation_urn(api, target_urn, mailbox_urn)
    if not conversation_urn:
        conversation_urn = find_conversation_urn_via_navigation(session, target_urn)
    if not conversation_urn:
        logger.error("API send failed for %s → no conversation found", public_identifier)
        return False

    try:
        send_message(api, conversation_urn, message, mailbox_urn)
        logger.info("Message sent to %s (API fallback)", public_identifier)
        return True
    except Exception as e:
        logger.error("API send failed for %s → %s", public_identifier, e)
        return False


if __name__ == "__main__":
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Debug LinkedIn messaging search results")
    parser.add_argument("--name", required=True, help="Full name to search for")
    args = parser.parse_args()
    session = cli_session(args)
    session.ensure_browser()

    print(f"Searching for '{args.name}' ...")

    goto_page(
        session,
        action=lambda: session.page.goto(LINKEDIN_MESSAGING_URL),
        expected_url_pattern="/messaging",
        timeout=30_000,
        error_message="Error opening messaging",
    )

    conn_input = _find(session.page, "connections_input").first
    conn_input.fill("")
    session.wait(0.5, 1)
    human_type(conn_input, args.name, min_delay=10, max_delay=50)
    session.wait(3, 4)

    rows = _find(session.page, "search_result_row")
    count = rows.count()
    print(f"\n=== Found {count} result rows ===\n")
    for i in range(min(count, 3)):
        row = rows.nth(i)
        print(f"--- Row {i} inner_text ---")
        print(row.inner_text(timeout=5_000))
        print(f"\n--- Row {i} outer_html ---")
        print(row.evaluate("el => el.outerHTML"))
        print()
