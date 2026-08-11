# linkedin/api/client.py
"""Instagram session client — Playwright UI scrape + optional in-page GraphQL.

Profile enrichment prefers the public web profile page; when Instagram embeds
JSON in page scripts we parse it. Fragile selectors are marked TODO.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from linkedin.browser.nav import goto_page
from linkedin.exceptions import AuthenticationError
from linkedin.url_utils import public_id_to_url, url_to_public_id

logger = logging.getLogger(__name__)

INSTAGRAM_REQUEST_TIMEOUT_MS = 30_000


class _FetchResponse:
    """Thin wrapper around the dict returned by page.evaluate(fetch(...))."""

    __slots__ = ("status", "ok", "_text")

    def __init__(self, raw: dict):
        self.status: int = raw["status"]
        self.ok: bool = raw["ok"]
        self._text: str = raw["body"]

    def json(self) -> Any:
        return json.loads(self._text)

    def text(self) -> str:
        return self._text


def _split_display_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _parse_count(text: str) -> int | None:
    if not text:
        return None
    cleaned = text.strip().replace(",", "").upper()
    mult = 1
    if cleaned.endswith("K"):
        mult = 1_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("M"):
        mult = 1_000_000
        cleaned = cleaned[:-1]
    try:
        return int(float(cleaned) * mult)
    except ValueError:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None


class PlaywrightInstagramAPI:
    """Instagram enrichment client bound to an authenticated Playwright session."""

    def __init__(
        self,
        session: "AccountSession",
        timeout_ms: int = INSTAGRAM_REQUEST_TIMEOUT_MS,
    ):
        self.session = session
        self.page = session.page
        self.context = session.context
        self.timeout_ms = timeout_ms

    def _fetch(self, method: str, url: str, headers: dict | None = None,
               body: str | None = None) -> _FetchResponse:
        raw = self.page.evaluate(
            """([method, url, headers, body, timeoutMs]) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                const init = {method, headers: headers || {}, credentials: "include",
                              signal: controller.signal};
                if (body !== null) init.body = body;
                return fetch(url, init).then(async r => {
                    clearTimeout(timer);
                    return {status: r.status, ok: r.ok, body: await r.text()};
                });
            }""",
            [method, url, headers or {}, body, self.timeout_ms],
        )
        return _FetchResponse(raw)

    def get(self, url: str, *, headers: dict | None = None) -> _FetchResponse:
        return self._fetch("GET", url, headers=headers)

    def _ensure_logged_in(self):
        if self.page.locator('input[name="username"]:visible').count() > 0:
            raise AuthenticationError("Instagram session expired (login form visible).")

    def _scrape_profile_from_dom(self, username: str) -> dict | None:
        page = self.page
        # TODO: header stats / bio selectors drift often
        full_name = ""
        bio = ""
        external_url = ""
        followers = None
        following = None
        posts = None
        is_private = False
        is_verified = False

        try:
            # Common pattern: h2 = username, nearby span/header has display name
            name_loc = page.locator("header section span, header h1, main header span").filter(
                has_not_text=username
            )
            if name_loc.count() > 0:
                for i in range(min(name_loc.count(), 8)):
                    txt = (name_loc.nth(i).inner_text() or "").strip()
                    if txt and txt.lower() != username.lower() and len(txt) < 120:
                        full_name = txt
                        break
        except Exception:
            pass

        try:
            bio_candidates = page.locator('header section > div span, header .-vDIg span, header section span')
            # Prefer a longer bio-like block
            best = ""
            for i in range(min(bio_candidates.count(), 20)):
                txt = (bio_candidates.nth(i).inner_text() or "").strip()
                if len(txt) > len(best) and txt.lower() != (full_name or "").lower():
                    best = txt
            bio = best
        except Exception:
            pass

        try:
            link = page.locator('header a[href^="http"]:not([href*="instagram.com"])').first
            if link.count() > 0:
                external_url = link.get_attribute("href") or ""
        except Exception:
            pass

        try:
            # Stats often appear as list items: posts / followers / following
            stats = page.locator("header ul li, header section ul li")
            for i in range(min(stats.count(), 6)):
                txt = (stats.nth(i).inner_text() or "").strip().lower()
                num = _parse_count(txt.split()[0] if txt else "")
                if "follower" in txt:
                    followers = num
                elif "following" in txt:
                    following = num
                elif "post" in txt:
                    posts = num
        except Exception:
            pass

        try:
            if page.get_by_text("This account is private", exact=False).count() > 0:
                is_private = True
        except Exception:
            pass

        try:
            if page.locator('svg[aria-label="Verified"], [title="Verified"]').count() > 0:
                is_verified = True
        except Exception:
            pass

        first, last = _split_display_name(full_name or username)
        company = ""
        # Heuristic: first URL host or bio fragment as company-ish signal
        if external_url:
            try:
                from urllib.parse import urlparse
                host = urlparse(external_url).netloc.replace("www.", "")
                company = host.split(".")[0].title() if host else ""
            except Exception:
                company = ""

        return {
            "public_identifier": username,
            "username": username,
            "urn": f"instagram:{username}",
            "first_name": first,
            "last_name": last,
            "headline": bio[:280] if bio else "",
            "summary": bio or "",
            "biography": bio or "",
            "external_url": external_url or "",
            "follower_count": followers,
            "following_count": following,
            "media_count": posts,
            "is_private": is_private,
            "is_verified": is_verified,
            "location_name": "",
            "industry": {},
            "positions": (
                [{"title": "", "company_name": company, "location": "", "description": ""}]
                if company
                else []
            ),
            "educations": [],
            "connection_degree": None,
            "follows_viewer": None,
            "followed_by_viewer": None,
        }

    def _try_web_profile_info(self, username: str) -> dict | None:
        """Best-effort in-page GraphQL/web_profile_info (may 404 without proper headers)."""
        # TODO: Instagram frequently changes /api/v1/users/web_profile_info/ requirements.
        try:
            res = self.get(
                f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
                headers={
                    "accept": "*/*",
                    "x-ig-app-id": "936619743392459",
                    "x-requested-with": "XMLHttpRequest",
                },
            )
        except Exception as exc:
            logger.debug("web_profile_info fetch failed for %s: %s", username, exc)
            return None

        if res.status == 401:
            raise AuthenticationError("Instagram API returned 401 Unauthorized.")
        if not res.ok:
            logger.debug("web_profile_info HTTP %s for %s", res.status, username)
            return None

        try:
            data = res.json()
            user = (data.get("data") or {}).get("user") or {}
        except Exception:
            return None
        if not user:
            return None

        full_name = user.get("full_name") or username
        first, last = _split_display_name(full_name)
        bio = user.get("biography") or ""
        company = ""
        ext = ""
        bio_links = user.get("bio_links") or []
        if bio_links:
            ext = bio_links[0].get("url") or ""
        elif user.get("external_url"):
            ext = user.get("external_url") or ""

        return {
            "public_identifier": user.get("username") or username,
            "username": user.get("username") or username,
            "urn": f"instagram:{user.get('id') or username}",
            "instagram_id": str(user.get("id") or ""),
            "first_name": first,
            "last_name": last,
            "headline": bio[:280],
            "summary": bio,
            "biography": bio,
            "external_url": ext,
            "follower_count": (user.get("edge_followed_by") or {}).get("count"),
            "following_count": (user.get("edge_follow") or {}).get("count"),
            "media_count": (user.get("edge_owner_to_timeline_media") or {}).get("count"),
            "is_private": bool(user.get("is_private")),
            "is_verified": bool(user.get("is_verified")),
            "is_business_account": bool(user.get("is_business_account")),
            "category_name": user.get("category_name") or "",
            "location_name": "",
            "industry": {"name": user.get("category_name") or ""},
            "positions": (
                [{"title": user.get("category_name") or "", "company_name": company or full_name,
                  "location": "", "description": bio}]
                if bio or user.get("category_name")
                else []
            ),
            "educations": [],
            "connection_degree": None,
            "follows_viewer": user.get("follows_viewer"),
            "followed_by_viewer": user.get("followed_by_viewer"),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(IOError),
        reraise=True,
    )
    def get_profile(
        self,
        public_identifier: Optional[str] = None,
        profile_url: Optional[str] = None,
    ) -> tuple[None, None] | tuple[dict, Any]:
        if not public_identifier and profile_url:
            public_identifier = url_to_public_id(profile_url)
        if not public_identifier:
            raise ValueError("Need public_identifier or profile_url")

        username = public_identifier.lstrip("@")
        url = public_id_to_url(username)
        self.session.ensure_browser()
        self.page = self.session.page

        goto_page(
            self.session,
            action=lambda: self.page.goto(url),
            expected_url_pattern=f"/{username}",
            error_message="Failed to open Instagram profile",
        )
        self._ensure_logged_in()

        profile = self._try_web_profile_info(username)
        raw: Any = {"source": "web_profile_info"} if profile else {"source": "dom"}
        if not profile:
            profile = self._scrape_profile_from_dom(username)
            raw = {"source": "dom", "url": self.page.url}

        if not profile:
            return None, None

        logger.info("Instagram profile enriched → %s", username)
        return profile, raw

    def get_follow_relationship(self, public_identifier: str) -> dict:
        """Return follow relationship flags when available."""
        profile, _ = self.get_profile(public_identifier=public_identifier)
        if not profile:
            return {"followed_by_viewer": None, "follows_viewer": None}
        return {
            "followed_by_viewer": profile.get("followed_by_viewer"),
            "follows_viewer": profile.get("follows_viewer"),
        }

    # Back-compat for older status checks that asked for a connection "degree".
    def get_connection_degree(self, public_identifier: str) -> int | None:
        """Map Instagram mutual/follow-back to a pseudo degree.

        1 = they follow us or Message is available (treated as connected).
        None = unknown.
        """
        rel = self.get_follow_relationship(public_identifier)
        if rel.get("follows_viewer") is True:
            return 1
        return None
