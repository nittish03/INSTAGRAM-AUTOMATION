# linkedin/browser/login.py
"""Instagram login + Playwright session bootstrap."""
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
    bot_pacing_delay_seconds,
)
from linkedin.exceptions import AuthenticationError

CHALLENGE_URL_FRAGMENTS = (
    "/challenge/",
    "/accounts/login/two_factor",
    "/auth_platform/",
    "checkpoint",
)
MANUAL_CHALLENGE_TIMEOUT_S = 5 * 60

logger = logging.getLogger(__name__)

INSTAGRAM_LOGIN_URL = "https://www.instagram.com/accounts/login/"
INSTAGRAM_HOME_URL = "https://www.instagram.com/"

# TODO: Instagram A/B tests login markup — keep ordered fallbacks.
SELECTORS = {
    "email": [
        'input[name="username"]',
        'input[aria-label*="username" i]',
        'input[aria-label*="phone" i]',
        'input[aria-label*="email" i]',
        'input[autocomplete="username"]',
        'input[type="text"]',
    ],
    "password": [
        'input[name="password"]',
        'input[aria-label*="Password" i]',
        'input[type="password"]',
        'input[autocomplete="current-password"]',
    ],
    "submit": [
        'button[type="submit"]',
        'button:has-text("Log in")',
        'button:has-text("Log In")',
    ],
}

CHALLENGE_SELECTORS = [
    'input[name="verificationCode"]',
    'input[aria-label*="Security code" i]',
    'input[aria-label*="Confirmation code" i]',
    'button:has-text("Confirm")',
    'h2:has-text("Suspicious")',
    'h1:has-text("Enter Confirmation Code")',
]


def _first_visible(page, selectors: list[str], timeout_ms: int = 5000):
    for selector in selectors:
        locator = page.locator(f"{selector}:visible").first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except PlaywrightTimeoutError:
            continue
    return None


def _clear_and_human_type(locator, text: str):
    try:
        locator.click()
        locator.fill("")
    except Exception:
        pass
    human_type(locator, text)


def _login_input_summary(page) -> str:
    try:
        return page.locator("input").evaluate_all(
            """els => els.map((el, idx) => ({
                idx,
                type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '',
                id: el.getAttribute('id') || '',
                autocomplete: el.getAttribute('autocomplete') || '',
                placeholder: el.getAttribute('placeholder') || '',
                aria: el.getAttribute('aria-label') || '',
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
            }))"""
        )
    except Exception as exc:  # pragma: no cover - diagnostic only
        return f"<input summary unavailable: {exc}>"


def _raise_auth_diagnostic(page, reason: str):
    title = ""
    try:
        title = page.title()
    except Exception:  # pragma: no cover - diagnostic only
        title = "<unavailable>"
    raise AuthenticationError(
        f"{reason}. URL={page.url!r} TITLE={title!r} INPUTS={_login_input_summary(page)!r}"
    )


def _is_challenge_url(url: str) -> bool:
    return any(frag in (url or "") for frag in CHALLENGE_URL_FRAGMENTS)


def _is_home_url(url: str) -> bool:
    """True when the browser appears to be past login on Instagram home/app."""
    if not url:
        return False
    if "/accounts/login" in url:
        return False
    if _is_challenge_url(url):
        return False
    return "instagram.com" in url


def _dismiss_post_login_modals(page):
    """Best-effort dismiss of 'Save login info' / 'Turn on notifications' dialogs."""
    for label in ("Not Now", "Not now", "Cancel"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
        except Exception:
            continue


def _wait_for_home_with_manual_challenge(page, timeout_s: int = MANUAL_CHALLENGE_TIMEOUT_S):
    deadline = time.time() + timeout_s
    notified = False
    while time.time() < deadline:
        try:
            current = page.url
        except Exception:
            current = ""

        if _is_home_url(current) and not _is_challenge_url(current):
            # Confirm we are not still on a login form
            if page.locator('input[name="username"]:visible').count() == 0:
                _dismiss_post_login_modals(page)
                return

        if (_is_challenge_url(current) or _first_visible(page, CHALLENGE_SELECTORS, timeout_ms=500)) and not notified:
            logger.warning(
                colored(
                    "Instagram security checkpoint detected. Please complete the "
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
        "Login did not reach Instagram home within "
        f"{timeout_s}s. Last URL: {page.url!r}. "
        "If Instagram showed a security challenge, complete it manually next time "
        "or use a fresh, verified account."
    )


def playwright_login(session):
    page = session.page
    profile = session.instagram_profile
    logger.info(colored("Fresh Instagram login starting", "cyan") + f" for {session}")

    try:
        page.goto(INSTAGRAM_LOGIN_URL, timeout=BROWSER_LOGIN_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        if not (_is_home_url(page.url) or "/accounts/login" in page.url or _is_challenge_url(page.url)):
            _raise_auth_diagnostic(page, "Failed to load Instagram login page")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except PlaywrightTimeoutError:
        logger.debug("Login page domcontentloaded timed out; continuing with field lookup")

    try:
        page.wait_for_url(
            lambda url: _is_home_url(url) or "/accounts/login" in url or _is_challenge_url(url),
            timeout=5000,
        )
    except PlaywrightTimeoutError:
        pass
    if _is_home_url(page.url) and page.locator('input[name="username"]:visible').count() == 0:
        logger.info(colored("Instagram session already authenticated", "green") + f" for {session}")
        _dismiss_post_login_modals(page)
        return

    email_input = _first_visible(page, SELECTORS["email"], timeout_ms=15000)
    if not email_input:
        if _is_home_url(page.url):
            logger.info(colored("Instagram session authenticated after manual login", "green") + f" for {session}")
            _dismiss_post_login_modals(page)
            return
        if _first_visible(page, CHALLENGE_SELECTORS, timeout_ms=1500):
            _wait_for_home_with_manual_challenge(page)
            logger.info(colored("Instagram challenge completed", "green") + f" for {session}")
            return
        _raise_auth_diagnostic(page, "Instagram username field not found")

    logger.info("Typing Instagram username for %s", session)
    _clear_and_human_type(email_input, profile.instagram_username)
    session.wait()

    password_input = _first_visible(page, SELECTORS["password"], timeout_ms=8000)
    if not password_input:
        _raise_auth_diagnostic(page, "Instagram password field not found")

    logger.info("Typing Instagram password for %s", session)
    _clear_and_human_type(password_input, profile.instagram_password)

    session.wait()
    submit_button = _first_visible(page, SELECTORS["submit"], timeout_ms=7000)
    if not submit_button:
        _raise_auth_diagnostic(page, "Instagram submit button not found")

    submit_button.click()
    _wait_for_home_with_manual_challenge(page)
    logger.debug("Instagram login navigation complete: %s", page.url)


def launch_browser(storage_state=None):
    logger.debug("Launching Playwright (headless=%s)", PLAYWRIGHT_HEADLESS)
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=PLAYWRIGHT_HEADLESS,
        slow_mo=bot_pacing_delay_seconds(BROWSER_SLOW_MO),
    )
    context = browser.new_context(storage_state=storage_state)
    context.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
    Stealth().apply_stealth_sync(context)
    page = context.new_page()
    return page, context, browser, playwright


def _save_cookies(session):
    """Persist Playwright storage state (cookies) to the DB."""
    state = session.context.storage_state()
    session.instagram_profile.cookie_data = state
    session.instagram_profile.save(update_fields=["cookie_data"])


def start_browser_session(session):
    logger.debug("Configuring Instagram browser for %s", session)

    session.instagram_profile.refresh_from_db(fields=["cookie_data"])
    cookie_data = session.instagram_profile.cookie_data

    storage_state = cookie_data if cookie_data else None
    if storage_state:
        logger.info("Loading saved Instagram session for %s", session)

    session.page, session.context, session.browser, session.playwright = launch_browser(storage_state=storage_state)

    if not storage_state:
        playwright_login(session)
        _save_cookies(session)
        logger.info(colored("Login successful – session saved", "green", attrs=["bold"]))
    else:
        try:
            goto_page(
                session,
                action=lambda: session.page.goto(INSTAGRAM_HOME_URL),
                expected_url_pattern="instagram.com",
                timeout=BROWSER_DEFAULT_TIMEOUT_MS,
                error_message="Saved Instagram session invalid",
            )
            if session.page.locator('input[name="username"]:visible').count() > 0:
                raise RuntimeError("Saved session redirected to login")
        except RuntimeError as exc:
            logger.warning("Saved Instagram session invalid for %s: %s", session, exc)
            playwright_login(session)
            _save_cookies(session)
            logger.info(colored("Login successful – refreshed saved session", "green", attrs=["bold"]))

    session.page.wait_for_load_state("load")
    _dismiss_post_login_modals(session.page)
    logger.info(colored("Browser ready", "green", attrs=["bold"]))


if __name__ == "__main__":
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Start an Instagram browser session")
    args = parser.parse_args()
    session = cli_session(args)
    session.ensure_browser()

    start_browser_session(session=session)
    print("Logged in! Close browser manually.")
    session.page.pause()
