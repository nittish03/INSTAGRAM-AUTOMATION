# linkedin/setup/self_profile.py
"""Discover and persist the logged-in user's own Instagram profile."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def discover_self_profile(session) -> dict:
    """Fetch the logged-in user's Instagram profile and persist as self_lead.

    Creates a disqualified Lead for the real profile (so auto-discovery
    won't target it) and links it as ``instagram_profile.self_lead``.
    """
    from crm.models import Lead
    from linkedin.api.client import PlaywrightInstagramAPI
    from linkedin.exceptions import AuthenticationError
    from linkedin.url_utils import public_id_to_url

    session.ensure_browser()
    page = session.page
    username = (session.instagram_profile.instagram_username or "").lstrip("@")

    # Prefer navigating to own profile via the logged-in account link
    api = PlaywrightInstagramAPI(session=session)
    profile = None
    raw = None

    # Try username from credentials first
    if username and "/" not in username and "@" not in username.replace("@", ""):
        # Emails as username won't work as IG handles — detect later from UI
        if "." not in username or username.count(".") < 2:
            try:
                profile, raw = api.get_profile(public_identifier=username)
            except Exception as exc:
                logger.debug("Self-profile by credential username failed: %s", exc)

    if not profile:
        # Click profile icon /accounts or extract from home
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30_000)
            session.wait()
            # Common: link to /username/ in nav
            for sel in (
                'a[href*="/"][href$="/"]:has(img[alt*="profile" i])',
                'svg[aria-label="Profile"]',
                'a[href^="/"][role="link"]:has(img)',
            ):
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=3000)
                        session.wait()
                        break
                    except Exception:
                        continue
            from linkedin.url_utils import url_to_public_id

            handle = url_to_public_id(page.url)
            if handle:
                profile, raw = api.get_profile(public_identifier=handle)
        except Exception as exc:
            logger.debug("Self-profile UI discovery failed: %s", exc)

    if not profile:
        raise AuthenticationError("Could not fetch own Instagram profile")

    real_id = profile["public_identifier"]
    real_url = public_id_to_url(real_id)

    lead, _ = Lead.objects.update_or_create(
        public_identifier=real_id,
        defaults={
            "instagram_url": real_url,
            "first_name": profile.get("first_name", ""),
            "last_name": profile.get("last_name", ""),
            "disqualified": True,
            "profile_data": profile,
        },
    )
    logger.info("Self-profile discovered: %s", real_url)

    session.instagram_profile.self_lead = lead
    session.instagram_profile.save(update_fields=["self_lead"])
    return profile
