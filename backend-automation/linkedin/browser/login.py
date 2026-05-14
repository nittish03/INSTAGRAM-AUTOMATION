# linkedin/browser/login.py
import logging
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from termcolor import colored

from linkedin.browser.nav import goto_page, human_type
from linkedin.conf import (
    BROWSER_DEFAULT_TIMEOUT_MS,
    BROWSER_LOGIN_TIMEOUT_MS,
    BROWSER_SLOW_MO,
    PLAYWRIGHT_HEADLESS,
)
from linkedin.exceptions import AuthenticationError

CHALLENGE_URL_FRAGMENTS = (
    "/checkpoint/challenge",
    "/checkpoint/lg/login-submit",
    "/checkpoint/rm/",
    "/uas/captcha",
)
MANUAL_CHALLENGE_TIMEOUT_S = 5 * 60  # 5 minutes for the user to solve the challenge

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


def _is_challenge_url(url: str) -> bool:
    return any(frag in url for frag in CHALLENGE_URL_FRAGMENTS)


def _wait_for_feed_with_manual_challenge(page, timeout_s: int = MANUAL_CHALLENGE_TIMEOUT_S):
    """Poll the URL; if a checkpoint shows up, ask the user to solve it manually.

    Returns when URL contains '/feed'. Raises AuthenticationError on timeout.
    """
    deadline = time.time() + timeout_s
    notified = False
    while time.time() < deadline:
        try:
            current = page.url
        except Exception:
            current = ""

        if "/feed" in current:
            return

        if _is_challenge_url(current) and not notified:
            logger.warning(
                colored(
                    "LinkedIn security checkpoint detected. Please complete the "
                    "verification (captcha / 2FA / email code) in the open browser "
                    "window. Waiting up to %d minutes...",
                    "yellow",
                    attrs=["bold"],
                ),
                timeout_s // 60,
            )
            notified = True

        try:
            page.wait_for_timeout(2000)
        except Exception:
            time.sleep(2)

    raise AuthenticationError(
        "Login did not reach /feed within "
        f"{timeout_s}s. Last URL: {page.url!r}. "
        "If LinkedIn showed a security challenge, complete it manually next time "
        "or use a fresh, verified account."
    )


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

    submit_button.click()

    # Give LinkedIn a brief moment to settle. If it sends us to a challenge URL,
    # wait for the user to solve it manually instead of crashing the daemon.
    try:
        page.wait_for_url(
            lambda url: "/feed" in url or _is_challenge_url(url),
            timeout=BROWSER_LOGIN_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        pass

    if "/feed" not in page.url:
        _wait_for_feed_with_manual_challenge(page)

    logger.debug("Login navigation complete: %s", page.url)


def launch_browser(storage_state=None):
    logger.debug("Launching Playwright (headless=%s)", PLAYWRIGHT_HEADLESS)
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=PLAYWRIGHT_HEADLESS,
        slow_mo=BROWSER_SLOW_MO,
    )
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
