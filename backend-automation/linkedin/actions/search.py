# linkedin/actions/search.py
"""Instagram search / hashtag discovery + profile visit helpers.

Discovery priority (account-centric):
1. Authenticated web topsearch / users-search APIs (Accounts results)
2. Search typeahead UI (Accounts rows)
3. Optional post-grid author harvest (last resort for #hashtags)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict
from urllib.parse import quote

from linkedin.browser.nav import (
    extract_author_from_post_page,
    extract_post_urls,
    extract_profile_urls,
    goto_page,
    human_type,
)
from linkedin.db.leads import discover_and_enrich
from linkedin.url_utils import is_plausible_instagram_username, public_id_to_url, url_to_public_id

logger = logging.getLogger(__name__)

# Instagram web keyword search is a post grid; harvest authors from a capped set of posts.
_MAX_POSTS_PER_SEARCH = 8
_IG_APP_ID = "936619743392459"
_API_HEADERS = {
    "accept": "*/*",
    "x-ig-app-id": _IG_APP_ID,
    "x-requested-with": "XMLHttpRequest",
}

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


def _self_username(session: "AccountSession") -> str:
    try:
        handle = (getattr(session.instagram_profile, "username", None) or "").lstrip("@")
        if handle:
            return handle.lower()
    except Exception:
        pass
    try:
        lead = getattr(session.instagram_profile, "self_lead", None)
        if lead and getattr(lead, "public_identifier", None):
            return str(lead.public_identifier).lstrip("@").lower()
    except Exception:
        pass
    return ""


def _page_fetch(page, url: str, headers: dict | None = None) -> dict:
    """Authenticated in-page fetch (same cookies as the Playwright session)."""
    raw = page.evaluate(
        """([url, headers, timeoutMs]) => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            return fetch(url, {
                method: "GET",
                headers: headers || {},
                credentials: "include",
                signal: controller.signal,
            }).then(async r => {
                clearTimeout(timer);
                return {status: r.status, ok: r.ok, body: await r.text()};
            });
        }""",
        [url, headers or {}, 25_000],
    )
    return raw or {"status": 0, "ok": False, "body": ""}


def _usernames_from_topsearch_payload(data: Any) -> list[str]:
    """Parse topsearch / users-search JSON into usernames."""
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(name: str | None):
        if not name:
            return
        cleaned = str(name).lstrip("@").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            return
        if not is_plausible_instagram_username(cleaned):
            return
        seen.add(key)
        out.append(cleaned)

    users = data.get("users")
    if isinstance(users, list):
        for item in users:
            if not isinstance(item, dict):
                continue
            # topsearch: {"position": N, "user": {"username": "..."}}
            user = item.get("user") if isinstance(item.get("user"), dict) else item
            if isinstance(user, dict):
                _add(user.get("username"))

    # Some blended payloads nest users elsewhere.
    for key in ("list", "results", "accounts"):
        maybe = data.get(key)
        if isinstance(maybe, list):
            for item in maybe:
                if isinstance(item, dict):
                    user = item.get("user") if isinstance(item.get("user"), dict) else item
                    if isinstance(user, dict):
                        _add(user.get("username"))

    return out


def _search_users_via_api(session: "AccountSession", query: str) -> set[str]:
    """Prefer Instagram Accounts/People search APIs over post grids."""
    page = session.page
    if not page:
        return set()

    # Ensure we are on an Instagram origin so credentialed fetch works.
    try:
        if "instagram.com" not in (page.url or ""):
            goto_page(
                session,
                action=lambda: page.goto("https://www.instagram.com/"),
                expected_url_pattern="instagram.com",
                error_message="Failed to open Instagram for API search",
            )
    except Exception as exc:
        logger.debug("Could not ensure Instagram origin for API search: %s", exc)

    q = quote(query.strip().lstrip("#"))
    endpoints = [
        f"https://www.instagram.com/api/v1/web/search/topsearch/?context=blended&query={q}&include_reel=false&count=50",
        f"https://www.instagram.com/web/search/topsearch/?context=blended&query={q}&include_reel=false&count=50",
        f"https://www.instagram.com/api/v1/users/search/?q={q}&count=50",
    ]

    profile_urls: set[str] = set()
    self_user = _self_username(session)

    for endpoint in endpoints:
        try:
            raw = _page_fetch(page, endpoint, headers=_API_HEADERS)
        except Exception as exc:
            logger.debug("topsearch fetch failed for %s: %s", endpoint, exc)
            continue

        status = int(raw.get("status") or 0)
        body = raw.get("body") or ""
        if status == 401:
            logger.warning("Instagram search API returned 401 (session expired?)")
            break
        if status != 200 or not body:
            logger.debug("Search API HTTP %s for %s", status, endpoint.split("?")[0])
            continue

        try:
            data = json.loads(body)
        except Exception:
            logger.debug("Search API returned non-JSON for %s", endpoint.split("?")[0])
            continue

        usernames = _usernames_from_topsearch_payload(data)
        for name in usernames:
            if self_user and name.lower() == self_user:
                continue
            profile_urls.add(public_id_to_url(name))

        if profile_urls:
            logger.info(
                "Accounts API harvest: %d users via %s (query=%r)",
                len(profile_urls),
                endpoint.split("?")[0].replace("https://www.instagram.com", ""),
                query,
            )
            return profile_urls

    return profile_urls


def _find_search_input(page):
    for sel in SEARCH_INPUT_SELECTORS:
        loc = page.locator(f"{sel}:visible")
        if loc.count() > 0:
            return loc.first
    try:
        page.get_by_role("link", name="Search").first.click(timeout=3000)
        time.sleep(0.8)
    except Exception:
        pass
    for sel in SEARCH_INPUT_SELECTORS:
        loc = page.locator(f"{sel}:visible")
        if loc.count() > 0:
            return loc.first
    return None


def _extract_usernames_from_typeahead(page, *, self_user: str = "") -> set[str]:
    """Pull account handles from the live search typeahead / Accounts panel."""
    found: set[str] = set()
    skip = {self_user.lower()} if self_user else set()

    # Prefer result rows that look like accounts (avatar + @handle / username text).
    selectors = [
        'a[href^="/"][role="link"]',
        'div[role="dialog"] a[href^="/"]',
        'nav a[href^="/"]',
        'a[href^="/"]',
    ]
    for sel in selectors:
        try:
            links = page.locator(sel).all()
        except Exception:
            continue
        for link in links[:80]:
            try:
                href = link.get_attribute("href") or ""
            except Exception:
                continue
            pid = url_to_public_id(href)
            if not pid or pid.lower() in skip:
                continue
            if not is_plausible_instagram_username(pid):
                continue
            # Typeahead account rows usually also show the handle as text.
            try:
                txt = (link.inner_text() or "").strip().lower()
            except Exception:
                txt = ""
            handle = pid.lower()
            if txt and (handle in txt or f"@{handle}" in txt or "·" in txt or "followers" in txt):
                found.add(pid)
            elif txt == "" or handle == txt.split("\n", 1)[0].lstrip("@"):
                # Still accept clean single-segment profile hrefs from result lists.
                found.add(pid)
        if len(found) >= 5:
            break
    return found


def _search_users_via_typeahead(session: "AccountSession", query: str) -> set[str]:
    """Human-like Search box → Accounts typeahead extraction."""
    page = session.page
    self_user = _self_username(session)
    try:
        goto_page(
            session,
            action=lambda: page.goto("https://www.instagram.com/"),
            expected_url_pattern="instagram.com",
            error_message="Failed to open Instagram home for typeahead search",
        )
    except Exception as exc:
        logger.debug("Typeahead home nav failed: %s", exc)
        return set()

    session.wait(1, 2)
    search = _find_search_input(page)
    if search is None:
        logger.debug("Search input not found for typeahead")
        return set()

    try:
        search.click()
        try:
            search.fill("")
        except Exception:
            pass
        human_type(search, query.strip())
        session.wait(2, 3)
    except Exception as exc:
        logger.debug("Typeahead typing failed: %s", exc)
        return set()

    # Prefer Accounts / People tab when Instagram shows it.
    for label in ("Accounts", "People", "Users"):
        try:
            tab = page.get_by_role("tab", name=re.compile(label, re.I))
            if tab.count() > 0:
                tab.first.click(timeout=2000)
                session.wait(1, 2)
                break
            btn = page.get_by_text(re.compile(rf"^{label}$", re.I))
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                session.wait(1, 2)
                break
        except Exception:
            continue

    usernames = _extract_usernames_from_typeahead(page, self_user=self_user)
    urls = {public_id_to_url(u) for u in usernames}
    if urls:
        logger.info("Typeahead Accounts harvest: %d users (query=%r)", len(urls), query)
    return urls


def _initiate_keyword_grid(session: "AccountSession", keyword: str):
    """Open Instagram keyword/hashtag explore grid (post results — last resort)."""
    page = session.page
    raw = keyword.strip()
    if _is_hashtag(raw):
        tag = raw.lstrip("#").strip()
        keyword_url = f"https://www.instagram.com/explore/search/keyword/?q={quote('#' + tag)}"
        tags_url = f"https://www.instagram.com/explore/tags/{quote(tag)}/"
        try:
            goto_page(
                session,
                action=lambda: page.goto(keyword_url),
                expected_url_pattern=("/explore/search/", "/explore/tags/"),
                error_message="Failed to reach Instagram hashtag/search page",
            )
        except RuntimeError:
            goto_page(
                session,
                action=lambda: page.goto(tags_url),
                expected_url_pattern=("/explore/tags/", "/explore/search/"),
                error_message="Failed to reach Instagram hashtag page",
            )
        return

    url = f"https://www.instagram.com/explore/search/keyword/?q={quote(raw)}"
    goto_page(
        session,
        action=lambda: page.goto(url),
        expected_url_pattern="/explore/search/",
        error_message="Failed to reach Instagram keyword search",
    )


def _paginate_to_next_page(session: "AccountSession", page_num: int):
    """Instagram web search is infinite-scroll — scroll instead of page query params."""
    page = session.page
    logger.debug("Scrolling Instagram results (pass %s)", page_num)
    try:
        page.mouse.wheel(0, 2400)
    except Exception:
        page.evaluate("window.scrollBy(0, 2400)")
    session.wait(1, 2)


def _extract_post_authors(session: "AccountSession") -> set[str]:
    """Last-resort harvest: open a few posts from the keyword grid and take authors."""
    page = session.page
    self_user = _self_username(session)
    profile_urls: set[str] = set()
    post_urls: list[str] = []

    for i in range(3):
        try:
            for u in extract_profile_urls(page):
                pid = url_to_public_id(u)
                if pid and is_plausible_instagram_username(pid):
                    if not self_user or pid.lower() != self_user:
                        profile_urls.add(public_id_to_url(pid))
        except Exception as exc:
            logger.debug("URL extract attempt %s failed: %s", i + 1, exc)
        try:
            for post in extract_post_urls(page, limit=_MAX_POSTS_PER_SEARCH):
                if post not in post_urls:
                    post_urls.append(post)
        except Exception as exc:
            logger.debug("Post URL extract attempt %s failed: %s", i + 1, exc)
        if profile_urls or post_urls:
            break
        try:
            page.mouse.wheel(0, 1200)
        except Exception:
            pass
        time.sleep(1.0)

    search_page_url = page.url
    for post_url in post_urls[:_MAX_POSTS_PER_SEARCH]:
        try:
            goto_page(
                session,
                action=lambda u=post_url: page.goto(u),
                expected_url_pattern=("/p/", "/reel/"),
                error_message="Failed to open Instagram post from search grid",
            )
            author = extract_author_from_post_page(page, skip_usernames={self_user} if self_user else None)
            if author and is_plausible_instagram_username(author):
                if not self_user or author.lower() != self_user:
                    profile_urls.add(public_id_to_url(author))
                    logger.debug("Post author discovered → %s (from %s)", author, post_url)
        except Exception as exc:
            logger.debug("Post author harvest failed for %s: %s", post_url, exc)

    if search_page_url and ("/explore/search/" in search_page_url or "/explore/tags/" in search_page_url):
        try:
            goto_page(
                session,
                action=lambda: page.goto(search_page_url),
                expected_url_pattern=("/explore/search/", "/explore/tags/"),
                error_message="Failed to return to Instagram search results",
            )
        except Exception as exc:
            logger.debug("Could not return to search page: %s", exc)

    logger.info(
        "Post-grid harvest: %d profile URLs from %d posts + page links",
        len(profile_urls),
        min(len(post_urls), _MAX_POSTS_PER_SEARCH),
    )
    return profile_urls


def _simulate_human_search(session: "AccountSession", profile: Dict[str, Any]) -> bool:
    """Try to land on a profile via Instagram search (more human than direct URL)."""
    public_identifier = (profile.get("public_identifier") or "").lstrip("@")
    if not public_identifier:
        return False
    try:
        page = session.page
        goto_page(
            session,
            action=lambda: page.goto("https://www.instagram.com/"),
            expected_url_pattern="instagram.com",
            error_message="Failed to open Instagram for profile search",
        )
        session.wait()
        search = _find_search_input(page)
        if search is None:
            return False
        search.click()
        human_type(search, public_identifier)
        session.wait(1, 2)
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
    """Run account-first search and enrich newly discovered profiles.

    Returns number of profile URLs seen (not necessarily newly created leads).
    """
    session.ensure_browser()
    query = keyword.strip()
    if not query:
        return 0

    urls: set[str] = set()

    # 1) Accounts API (People/Users ranking) — primary path for multi-word business queries.
    if not _is_hashtag(query):
        urls |= _search_users_via_api(session, query)
        if not urls:
            urls |= _search_users_via_typeahead(session, query)

    # 2) Hashtags / empty account results → typeahead then post-grid authors.
    if not urls:
        if _is_hashtag(query):
            # Try accounts that match the tag text without '#'.
            bare = query.lstrip("#").strip()
            if bare:
                urls |= _search_users_via_api(session, bare)
                if not urls:
                    urls |= _search_users_via_typeahead(session, bare)

        try:
            _initiate_keyword_grid(session, query)
            for page_num in range(1, max_pages + 1):
                if page_num > 1:
                    _paginate_to_next_page(session, page_num)
                else:
                    session.wait(1, 2)
            urls |= _extract_post_authors(session)
        except Exception as exc:
            logger.warning("Keyword/hashtag grid harvest failed for %r: %s", query, exc)

    # Final junk filter before enrich.
    clean: set[str] = set()
    for u in urls:
        pid = url_to_public_id(u)
        if pid and is_plausible_instagram_username(pid):
            clean.add(public_id_to_url(pid))

    logger.info(
        "Search harvest: %d profile URLs for query=%r",
        len(clean),
        query,
    )
    if clean:
        discover_and_enrich(session, clean)
    return len(clean)


def search_people(session: "AccountSession", keyword: str, max_pages: int = 3) -> int:
    """Discovery entrypoint used by the pipeline (Accounts-first + hashtag fallback)."""
    return search_and_discover(session, keyword, max_pages=max_pages)


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
