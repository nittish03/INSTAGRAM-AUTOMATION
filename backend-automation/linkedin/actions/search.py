# linkedin/actions/search.py
"""Instagram search / hashtag discovery + profile visit helpers."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict
from urllib.parse import quote

from linkedin.browser.nav import extract_profile_urls, goto_page, human_type
from linkedin.db.leads import discover_and_enrich
from linkedin.url_utils import public_id_to_url, url_to_public_id

logger = logging.getLogger(__name__)

# TODO: Instagram search UI / URL shapes change frequently.
SEARCH_INPUT_SELECTORS = [
    'input[placeholder*="Search" i]',
    'input[aria-label*="Search" i]',
    'input[type="text"][placeholder]',
]


def _go_to_profile(session: "AccountSession", url: str, public_identifier: str):
    session.ensure_browser()
    if not session.page:
        raise RuntimeError("Browser page is unavailable after ensure_browser().")
    username = public_identifier.lstrip("@")
    if f"/{username}" in session.page.url.rstrip("/") and "/p/" not in session.page.url:
        return
    logger.debug("Direct navigation → %s", username)
    goto_page(
        session,
        action=lambda: session.page.goto(url if url else public_id_to_url(username)),
        expected_url_pattern=f"/{username}",
        error_message="Failed to navigate to the target Instagram profile",
    )


def visit_profile(session: "AccountSession", profile: Dict[str, Any]):
    public_identifier = (profile.get("public_identifier") or "").lstrip("@")
    session.ensure_browser()

    already_there = (
        f"/{public_identifier}" in (session.page.url or "")
        and "/p/" not in session.page.url
        and "/reel/" not in session.page.url
    )
    if already_there:
        return

    found_via_search = _simulate_human_search(session, profile)
    if not found_via_search:
        url = profile.get("url") or public_id_to_url(public_identifier)
        _go_to_profile(session, url, public_identifier)

    urls = extract_profile_urls(session.page)
    discover_and_enrich(session, urls)


def _is_hashtag(keyword: str) -> bool:
    return keyword.strip().startswith("#")


def _initiate_search(session: "AccountSession", keyword: str):
    """Open Instagram search results for people or a hashtag page."""
    page = session.page
    raw = keyword.strip()
    if _is_hashtag(raw):
        tag = raw.lstrip("#").strip()
        url = f"https://www.instagram.com/explore/tags/{quote(tag)}/"
        goto_page(
            session,
            action=lambda: page.goto(url),
            expected_url_pattern="/explore/tags/",
            error_message="Failed to reach Instagram hashtag page",
        )
        return

    # People/top search results page (web)
    url = f"https://www.instagram.com/explore/search/keyword/?q={quote(raw)}"
    try:
        goto_page(
            session,
            action=lambda: page.goto(url),
            expected_url_pattern="/explore/search/",
            error_message="Failed to reach Instagram keyword search",
        )
    except RuntimeError:
        # Fallback: home → type into search box
        goto_page(
            session,
            action=lambda: page.goto("https://www.instagram.com/"),
            expected_url_pattern="instagram.com",
            error_message="Failed to open Instagram home for search",
        )
        session.wait()
        search = None
        for sel in SEARCH_INPUT_SELECTORS:
            loc = page.locator(f"{sel}:visible")
            if loc.count() > 0:
                search = loc.first
                break
        if search is None:
            # Try clicking Search nav then input
            try:
                page.get_by_role("link", name="Search").first.click(timeout=3000)
                session.wait()
            except Exception:
                pass
            for sel in SEARCH_INPUT_SELECTORS:
                loc = page.locator(f"{sel}:visible")
                if loc.count() > 0:
                    search = loc.first
                    break
        if search is None:
            raise RuntimeError("Instagram search input not found")
        search.click()
        human_type(search, raw)
        session.wait(2, 4)


def _paginate_to_next_page(session: "AccountSession", page_num: int):
    """Instagram web search is infinite-scroll — scroll instead of page query params."""
    page = session.page
    logger.debug("Scrolling Instagram results (pass %s)", page_num)
    try:
        page.mouse.wheel(0, 2400)
    except Exception:
        page.evaluate("window.scrollBy(0, 2400)")
    session.wait(1, 2)


def _extract_search_urls_with_retry(session: "AccountSession", attempts: int = 3) -> set[str]:
    page = session.page
    urls: set[str] = set()
    for i in range(attempts):
        try:
            urls |= extract_profile_urls(page)
        except Exception as exc:
            logger.debug("URL extract attempt %s failed: %s", i + 1, exc)
        if urls:
            return urls
        try:
            page.mouse.wheel(0, 1200)
        except Exception:
            pass
        time.sleep(1.0)
    return urls


def _simulate_human_search(session: "AccountSession", profile: Dict[str, Any]) -> bool:
    """Try to land on a profile via Instagram search (more human than direct URL)."""
    public_identifier = (profile.get("public_identifier") or "").lstrip("@")
    if not public_identifier:
        return False
    try:
        _initiate_search(session, public_identifier)
        session.wait()
        # Click a result matching the username
        page = session.page
        candidates = page.locator(f'a[href="/{public_identifier}/"], a[href*="/{public_identifier}/"]')
        if candidates.count() == 0:
            return False
        candidates.first.click()
        session.wait()
        return f"/{public_identifier}" in (page.url or "")
    except Exception as exc:
        logger.debug("Human search simulation failed for %s: %s", public_identifier, exc)
        return False


def search_and_discover(session: "AccountSession", keyword: str, max_pages: int = 3) -> int:
    """Run keyword/hashtag search and enrich newly discovered profiles.

    Returns number of URLs seen across scrolls (not necessarily newly created leads).
    """
    session.ensure_browser()
    _initiate_search(session, keyword)
    all_urls: set[str] = set()
    for page_num in range(1, max_pages + 1):
        urls = _extract_search_urls_with_retry(session)
        all_urls |= urls
        discover_and_enrich(session, urls)
        if page_num < max_pages:
            _paginate_to_next_page(session, page_num + 1)
    return len(all_urls)


if __name__ == "__main__":
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Visit / search Instagram profiles")
    parser.add_argument("--profile", default=None, help="Username to visit")
    parser.add_argument("--keyword", default=None, help="Search keyword or #hashtag")
    args = parser.parse_args()
    session = cli_session(args)

    if args.keyword:
        n = search_and_discover(session, args.keyword)
        print(f"Discovered URLs seen: {n}")
    elif args.profile:
        visit_profile(
            session,
            {
                "url": public_id_to_url(args.profile),
                "public_identifier": args.profile,
            },
        )
        print(f"Visited @{args.profile}")
    else:
        parser.print_help()
