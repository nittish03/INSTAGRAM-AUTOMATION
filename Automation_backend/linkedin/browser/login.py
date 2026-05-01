# linkedin/browser/login.py
import logging

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from termcolor import colored

from linkedin.browser.nav import goto_page, human_type
from linkedin.conf import (
    BROWSER_DEFAULT_TIMEOUT_MS,
    BROWSER_LOGIN_TIMEOUT_MS,
    BROWSER_SLOW_MO,
)
from linkedin.exceptions import AuthenticationError

logger = logging.getLogger(__name__)

LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"

SELECTORS = {
    "email": [
        'input#username',
        'input[name="session_key"]',
        'input[autocomplete="username"]',
        'input[name="username"]',
    ],
    "password": [
        'input#password',
        'input[name="session_password"]',
        'input[autocomplete="current-password"]',
        'input[name="password"]',
    ],
    "submit": [
        'button[type="submit"]',
        'button[data-litms-control-urn*="login-submit"]',
        'button[aria-label*="Sign in"]',
    ],
}

CHALLENGE_SELECTORS = [
    'iframe[src*="captcha"]',
    'input#captcha-internal',
    'input[name="pin"]',
    'h1:has-text("Security verification")',
    'h1:has-text("Let’s do a quick security check")',
]


def _first_visible(page, selectors: list[str], timeout_ms: int = 5000):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except PlaywrightTimeoutError:
            continue
    return None


def _raise_auth_diagnostic(page, reason: str):
    title = ""
    try:
        title = page.title()
    except Exception:  # pragma: no cover - diagnostic only
        title = "<unavailable>"
    raise AuthenticationError(f"{reason}. URL={page.url!r} TITLE={title!r}")


def playwright_login(session):
    page = session.page
    lp = session.linkedin_profile
    logger.info(colored("Fresh login sequence starting", "cyan") + f" for {session}")

    goto_page(
        session,
        action=lambda: page.goto(LINKEDIN_LOGIN_URL),
        expected_url_pattern="/login",
        error_message="Failed to load login page",
    )

    email_input = _first_visible(page, SELECTORS["email"], timeout_ms=10000)
    password_input = _first_visible(page, SELECTORS["password"], timeout_ms=3000)
    if not email_input or not password_input:
        if _first_visible(page, CHALLENGE_SELECTORS, timeout_ms=1500):
            _raise_auth_diagnostic(page, "LinkedIn presented a challenge/captcha page")
        _raise_auth_diagnostic(page, "LinkedIn login form fields not found")

    human_type(email_input, lp.linkedin_username)
    session.wait()
    human_type(password_input, lp.linkedin_password)

    session.wait()
    submit_button = _first_visible(page, SELECTORS["submit"], timeout_ms=7000)
    if not submit_button:
        _raise_auth_diagnostic(page, "LinkedIn submit button not found")

    goto_page(
        session,
        action=lambda: submit_button.click(),
        expected_url_pattern="/feed",
        timeout=BROWSER_LOGIN_TIMEOUT_MS,
        error_message="Login failed – no redirect to feed",
    )


def launch_browser(storage_state=None):
    logger.debug("Launching Playwright")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False, slow_mo=BROWSER_SLOW_MO)
    context = browser.new_context(storage_state=storage_state)
    context.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
    Stealth().apply_stealth_sync(context)
    page = context.new_page()
    return page, context, browser, playwright


def _save_cookies(session):
    """Persist Playwright storage state (cookies) to the DB."""
    state = session.context.storage_state()
    session.linkedin_profile.cookie_data = state
    session.linkedin_profile.save(update_fields=["cookie_data"])


def start_browser_session(session):
    logger.debug("Configuring browser for %s", session)

    session.linkedin_profile.refresh_from_db(fields=["cookie_data"])
    cookie_data = session.linkedin_profile.cookie_data

    storage_state = cookie_data if cookie_data else None
    if storage_state:
        logger.info("Loading saved session for %s", session)

    session.page, session.context, session.browser, session.playwright = launch_browser(storage_state=storage_state)

    if not storage_state:
        playwright_login(session)
        _save_cookies(session)
        logger.info(colored("Login successful – session saved", "green", attrs=["bold"]))
    else:
        goto_page(
            session,
            action=lambda: session.page.goto(LINKEDIN_FEED_URL),
            expected_url_pattern="/feed",
            timeout=BROWSER_DEFAULT_TIMEOUT_MS,
            error_message="Saved session invalid",
        )

    session.page.wait_for_load_state("load")
    logger.info(colored("Browser ready", "green", attrs=["bold"]))


if __name__ == "__main__":
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Start a LinkedIn browser session")
    args = parser.parse_args()
    session = cli_session(args)
    session.ensure_browser()

    start_browser_session(session=session)
    print("Logged in! Close browser manually.")
    session.page.pause()
