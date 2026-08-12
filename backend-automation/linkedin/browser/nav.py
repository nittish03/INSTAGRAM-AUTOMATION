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
    expected_url_pattern: str | tuple[str, ...],
    timeout: int = BROWSER_NAV_TIMEOUT_MS,
    error_message: str = "",
):
    patterns = (
        (expected_url_pattern,)
        if isinstance(expected_url_pattern, str)
        else tuple(expected_url_pattern)
    )

    def _url_matches(url: str) -> bool:
        decoded = unquote(url or "")
        return any(p in decoded for p in patterns)

    page = session.page
    try:
        action()
    except PlaywrightTimeoutError:
        # Instagram pages often keep resources pending; treat soft timeout if URL matches.
        current = unquote((session.page or page).url if (session.page or page) else "")
        if not _url_matches(current):
            raise
        logger.warning(
            "Navigation action timed out after reaching %s; continuing",
            current,
        )

    page = session.page
    if not page:
        return

    try:
        page.wait_for_url(lambda url: _url_matches(url), timeout=timeout)
    except PlaywrightTimeoutError:
        pass

    session.wait()

    current = unquote(page.url)
    if not _url_matches(current):
        if "/404" in current or "Page Not Found" in (page.title() or ""):
            raise SkipProfile(f"Profile returned 404 → {current}")
        expected = "' or '".join(patterns)
        raise RuntimeError(f"{error_message} → expected '{expected}' | got '{current}'")

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


def extract_post_urls(page, *, limit: int = 24) -> list[str]:
    """Collect `/p/` and `/reel/` URLs from keyword/hashtag result grids."""
    seen: set[str] = set()
    ordered: list[str] = []
    for link in page.locator('a[href*="/p/"], a[href*="/reel/"]').all():
        try:
            href = link.get_attribute("href") or ""
        except Exception:
            continue
        if not href:
            continue
        full_url = urljoin(page.url, href.strip())
        parsed = urlparse(full_url)
        path = parsed.path.rstrip("/") + "/"
        if "/p/" not in path and "/reel/" not in path:
            continue
        clean = parsed._replace(query="", fragment="", path=path).geturl()
        if clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
        if len(ordered) >= limit:
            break
    logger.debug("Extracted %d post/reel URLs from search grid", len(ordered))
    return ordered


def extract_author_from_post_page(page, *, skip_usernames: set[str] | None = None) -> str | None:
    """Best-effort author username from an opened Instagram post/reel page."""
    import re

    from linkedin.url_utils import url_to_public_id

    skip = {s.lstrip("@").lower() for s in (skip_usernames or set()) if s}

    def _accept(pid: str | None) -> str | None:
        if not pid:
            return None
        cleaned = pid.lstrip("@")
        if cleaned.lower() in skip:
            return None
        return cleaned

    # Header author link is the most reliable on post pages.
    for sel in (
        "article header a[href^='/']",
        "main header a[href^='/']",
        "header a[href^='/']",
        'a[role="link"][href^="/"]',
    ):
        try:
            for link in page.locator(sel).all()[:12]:
                href = link.get_attribute("href") or ""
                pid = _accept(url_to_public_id(urljoin(page.url, href)))
                if pid:
                    return pid
        except Exception:
            continue

    try:
        html = page.content()
    except Exception:
        html = ""

    # Prefer explicit owner blocks over the first generic username (often the viewer).
    for pat in (
        r'"owner"\s*:\s*\{[^{}]*?"username"\s*:\s*"([A-Za-z0-9._]+)"',
        r'"user"\s*:\s*\{[^{}]*?"username"\s*:\s*"([A-Za-z0-9._]+)"',
        r'"author"\s*:\s*\{[^{}]*?"username"\s*:\s*"([A-Za-z0-9._]+)"',
        r'content="https://www\.instagram\.com/([A-Za-z0-9._]+)/"',
    ):
        for match in re.finditer(pat, html, flags=re.I):
            pid = _accept(match.group(1))
            if pid:
                return pid

    for match in re.finditer(r'"username"\s*:\s*"([A-Za-z0-9._]+)"', html):
        pid = _accept(match.group(1))
        if pid:
            return pid
    return None


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
