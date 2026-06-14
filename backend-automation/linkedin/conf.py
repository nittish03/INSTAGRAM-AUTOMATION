# linkedin/conf.py
from __future__ import annotations

import os
from pathlib import Path


_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}
BOT_TIME_LIMITS_ENV = "BOT_TIME_LIMITS_ENABLED"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    normalized = str(raw).strip().lower()
    if normalized in _TRUE_ENV_VALUES:
        return True
    if normalized in _FALSE_ENV_VALUES:
        return False
    return default


def bot_time_limits_enabled() -> bool:
    """Whether local bot pacing, quotas, active windows, and runtime caps apply."""
    return _env_bool(BOT_TIME_LIMITS_ENV, True)


def bot_delay_seconds(seconds: float | int | None) -> float:
    """Return a bot pacing delay, or zero when time limits are disabled."""
    if not bot_time_limits_enabled():
        return 0.0
    return max(float(seconds or 0), 0.0)


def _playwright_headless() -> bool:
    """Whether Chromium runs headless (required on servers without a display).

    Set ``PLAYWRIGHT_HEADLESS=1`` (or ``true`` / ``yes`` / ``on``) on Linux VPS /
    containers. Set to ``0`` / ``false`` for a visible browser (local debugging).

    When unset: ``headless`` defaults to ``True`` if ``ENV=production``, else
    ``False`` so local dev keeps the current headed behavior.
    """
    raw = os.environ.get("PLAYWRIGHT_HEADLESS")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return os.environ.get("ENV", "").lower() == "production"


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent.parent

PROMPTS_DIR = Path(__file__).parent / "templates" / "prompts"

DIAGNOSTICS_DIR = Path("/tmp/leadpilot-diagnostics")

FASTEMBED_CACHE_DIR = ROOT_DIR / ".cache" / "fastembed"

FIXTURE_DIR = ROOT_DIR / "tests" / "fixtures"
FIXTURE_PROFILES_DIR = FIXTURE_DIR / "profiles"
FIXTURE_PAGES_DIR = FIXTURE_DIR / "pages"
DUMP_PAGES = False

MIN_DELAY = 20
MAX_DELAY = 45

# ----------------------------------------------------------------------
# Browser config
# ----------------------------------------------------------------------
PLAYWRIGHT_HEADLESS = _playwright_headless()
BROWSER_SLOW_MO = 350
BROWSER_DEFAULT_TIMEOUT_MS = 30_000
BROWSER_LOGIN_TIMEOUT_MS = 40_000
BROWSER_NAV_TIMEOUT_MS = 10_000
HUMAN_TYPE_MIN_DELAY_MS = 120
HUMAN_TYPE_MAX_DELAY_MS = 380

# ----------------------------------------------------------------------
# Onboarding defaults (shown to user during interactive setup)
# ----------------------------------------------------------------------
DEFAULT_CONNECT_DAILY_LIMIT = 3
DEFAULT_CONNECT_WEEKLY_LIMIT = 12
DEFAULT_FOLLOW_UP_DAILY_LIMIT = 8

# ----------------------------------------------------------------------
# Active-hours schedule (daemon pauses outside this window)
# Set to False to run 24/7.
# ----------------------------------------------------------------------
ENABLE_ACTIVE_HOURS = True
ACTIVE_START_HOUR = 10   # inclusive, local time
ACTIVE_END_HOUR = 16     # exclusive, local time
ACTIVE_TIMEZONE = "Asia/Kolkata"
REST_DAYS = (5, 6)      # 0=Mon … 6=Sun; default Sat+Sun off

# ----------------------------------------------------------------------
# Campaign config (timing + ML defaults — hardcoded, no YAML)
# ----------------------------------------------------------------------
CAMPAIGN_CONFIG = {
    "check_pending_recheck_after_hours": 12,
    "enrich_min_interval": 1,
    "min_action_interval": 45 * 60,
    "daemon_max_runtime_seconds": 45 * 60,
    "qualification_n_mc_samples": 100,
    "min_ready_to_connect_prob": 0.9,
    "min_positive_pool_prob": 0.20,
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "connect_delay_seconds": 6 * 60 * 60,
    "connect_no_candidate_delay_seconds": 3 * 60 * 60,
    "reply_check_interval_seconds": 30 * 60,
    "reply_check_max_attempts": 8,
    "reply_check_window_seconds": 4 * 60 * 60,
}

# ----------------------------------------------------------------------
# Global OpenAI / LLM config (stored in DB via SiteConfig)
# ----------------------------------------------------------------------

def get_llm_config(user=None):
    """Return (llm_api_key, ai_model, llm_api_base) from the DB."""
    from linkedin.models import SiteConfig
    cfg = SiteConfig.load(user)
    return cfg.llm_api_key, cfg.ai_model, cfg.llm_api_base or None


def get_llm_site_config(user=None):
    """Return the SiteConfig object for LLM/provider setup."""
    from linkedin.models import SiteConfig
    return SiteConfig.load(user)


