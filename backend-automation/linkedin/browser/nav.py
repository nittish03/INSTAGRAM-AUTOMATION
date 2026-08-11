# linkedin/browser/nav.py
"""Shared Playwright navigation helpers for Instagram web."""
from __future__ import annotations

import logging
import random
import time
from urllib.parse import unquote, urlparse, urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from linkedin.conf import (
    BROWSER_NAV_TIMEOUT_MS,
    DUMP_PAGES,
    FIXTURE_PAGES_DIR,
    HUMAN_TYPE_MAX_DELAY_MS,
    HUMAN_TYPE_MIN_DELAY_MS,
    bot_sleep_enabled,
)
from linkedin.exceptions import SkipProfile

logger = logging.getLogger(__name__)


def goto_page(
    session,
    action,
    expected_url_pattern: str,
    timeout: int = BROWSER_NAV_TIMEOUT_MS,
    error_message: str = "",
):
    page = session.page
    try:
        action()
    except PlaywrightTimeoutError:
        # Instagram pages often keep resources pending; treat soft timeout if URL matches.
        current = unquote((session.page or page).url if (session.page or page) else "")
        if expected_url_pattern not in current:
            raise
        logger.warning(
            "Navigation action timed out after reaching %s; continuing",
            current,
        )

    page = session.page
    if not page:
        return

    try:
        page.wait_for_url(lambda url: expected_url_pattern in unquote(url), timeout=timeout)
    except PlaywrightTimeoutError:
        pass

    session.wait()

    current = unquote(page.url)
    if expected_url_pattern not in current:
        if "/404" in current or "Page Not Found" in (page.title() or ""):
            raise SkipProfile(f"Profile returned 404 → {current}")
        raise RuntimeError(f"{error_message} → expected '{expected_url_pattern}' | got '{current}'")

    logger.debug("Navigated to %s", page.url)


def extract_profile_urls(page) -> set[str]:
    """Extract Instagram profile URLs from the current page (search / explore / tags)."""
    from linkedin.url_utils import public_id_to_url, url_to_public_id

    urls: set[str] = set()
    for link in page.locator('a[href^="/"], a[href*="instagram.com/"]').all():
        try:
            href = link.get_attribute("href") or ""
        except Exception:
            continue
        if not href:
            continue
        full_url = urljoin(page.url, href.strip())
        clean = urlparse(full_url)._replace(query="", fragment="").geturl()
        pid = url_to_public_id(clean)
        if not pid:
            continue
        urls.add(public_id_to_url(pid))
    logger.debug("Extracted %d unique Instagram profiles", len(urls))
    return urls


# Back-compat alias used by older discovery call sites.
extract_in_urls = extract_profile_urls


# TODO: Instagram A/B tests profile header markup frequently.
PROFILE_HEADER_SELECTORS = [
    "main header",
    "header section",
    'section:has(header)',
    "article header",
    "main section header",
]


def find_first_visible(page, selectors: list[str]):
    """Try selectors in order, return first locator that matches."""
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            return locator.first
    return None


def find_top_card(session, timeout_ms: int = 10_000):
    """Return the Instagram profile header region (legacy name: top card)."""
    page = session.page
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        header = find_first_visible(page, PROFILE_HEADER_SELECTORS)
        if header is not None:
            return header
        try:
            page.wait_for_timeout(300)
        except Exception:
            break
    logger.warning("Profile header not found on %s", page.url)
    raise SkipProfile("Instagram profile header not found")


def human_type(locator, text: str, min_delay: int = HUMAN_TYPE_MIN_DELAY_MS, max_delay: int = HUMAN_TYPE_MAX_DELAY_MS):
    """Type text with randomized per-keystroke delay to mimic human input."""
    delay = random.randint(min_delay, max_delay) if bot_sleep_enabled() else 0
    locator.type(text, delay=delay)


def dump_page_html(session: "AccountSession", profile: dict, category: str = "follow"):
    if not DUMP_PAGES:
        return
    dest = FIXTURE_PAGES_DIR / category
    dest.mkdir(parents=True, exist_ok=True)
    filepath = dest / f"{profile.get('public_identifier')}.html"
    html_content = session.page.content()
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info("Saved page snapshot → %s", filepath)
