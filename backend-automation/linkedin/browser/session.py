# linkedin/browser/session.py
from __future__ import annotations

import logging
import random
import time
from functools import cached_property

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from linkedin.conf import MIN_DELAY, MAX_DELAY, bot_sleep_enabled

logger = logging.getLogger(__name__)

# Primary Instagram auth cookie
_AUTH_COOKIE_NAME = "sessionid"


def random_sleep(min_val, max_val):
    if not bot_sleep_enabled():
        logger.debug("Pause skipped (sleep pacing disabled)")
        return
    delay = random.uniform(min_val, max_val)
    logger.debug("Pause: %.2fs", delay)
    time.sleep(delay)


class AccountSession:
    def __init__(self, instagram_profile):
        self.instagram_profile = instagram_profile
        self.django_user = instagram_profile.user

        # Active campaign — set by the daemon before each lane execution
        self.campaign = None

        # Playwright objects – created on first access or after crash
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None

    @cached_property
    def campaigns(self):
        """All campaigns this user belongs to (cached)."""
        from linkedin.models import Campaign
        return list(Campaign.objects.filter(users=self.django_user))

    def ensure_browser(self):
        """Launch or recover browser + login if needed. Call before using .page"""
        from linkedin.browser.login import start_browser_session

        if not self.page or self.page.is_closed():
            logger.debug("Launching/recovering browser for %s", self)
            start_browser_session(session=self)
        else:
            self._maybe_refresh_cookies()

    @cached_property
    def self_profile(self) -> dict:
        """Lazy accessor: return the authenticated user's profile dict (cached)."""
        self.instagram_profile.refresh_from_db(fields=["self_lead"])
        lead = self.instagram_profile.self_lead
        if lead and lead.profile_data and lead.profile_data.get("username"):
            return lead.profile_data

        from linkedin.setup.self_profile import discover_self_profile

        self.ensure_browser()
        return discover_self_profile(self)

    def wait(self, min_delay=MIN_DELAY, max_delay=MAX_DELAY):
        random_sleep(min_delay, max_delay)
        if self.page and not self.page.is_closed():
            try:
                self.page.wait_for_load_state("load", timeout=10_000)
            except PlaywrightTimeoutError:
                logger.debug("Page load state timed out on %s; continuing", self.page.url)

    def _maybe_refresh_cookies(self):
        """Re-login if the sessionid auth cookie in the saved DB state is expired."""
        from linkedin.browser.login import start_browser_session

        self.instagram_profile.refresh_from_db(fields=["cookie_data"])
        cookie_data = self.instagram_profile.cookie_data
        if not cookie_data:
            return
        for cookie in cookie_data.get("cookies", []):
            if cookie.get("name") == _AUTH_COOKIE_NAME:
                expires = cookie.get("expires", -1)
                if expires > 0 and expires < time.time():
                    logger.warning("Auth cookie expired for %s - re-authenticating", self)
                    self.close()
                    start_browser_session(session=self)
                return

    def close(self):
        if self.context:
            try:
                self.context.close()
                if self.browser:
                    self.browser.close()
                if self.playwright:
                    self.playwright.stop()
                logger.info("Browser closed gracefully (%s)", self)
            except Exception as e:
                logger.debug("Error closing browser: %s", e)
            finally:
                self.page = self.context = self.browser = self.playwright = None

        logger.info("Account session closed -> %s", self)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return self.instagram_profile.instagram_username
