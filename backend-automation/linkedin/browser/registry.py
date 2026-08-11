# linkedin/browser/registry.py
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_sessions: dict[int, "AccountSession"] = {}


def get_or_create_session(instagram_profile) -> "AccountSession":
    from linkedin.browser.session import AccountSession

    pk = instagram_profile.pk
    if pk not in _sessions:
        _sessions[pk] = AccountSession(instagram_profile)
        logger.debug("Created new account session for %s", instagram_profile)
    return _sessions[pk]


def get_first_active_profile(handle: str | None = None):
    """Return the first active InstagramProfile.

    When ``handle`` is provided the lookup is scoped to that Django user's
    profiles only (multi-tenant mode used by the dashboard's "Run Daemon"
    button). With no handle the daemon picks the first active profile
    globally — preserving the legacy single-tenant CLI behavior.
    """
    from linkedin.models import InstagramProfile

    qs = InstagramProfile.objects.filter(active=True).select_related("user")
    if handle:
        qs = qs.filter(user__username=handle)
    return qs.order_by("-created_at", "id").first()


def resolve_profile(username: str | None = None):
    """Resolve a InstagramProfile from an optional username, falling back to first active."""
    if username:
        from linkedin.models import InstagramProfile

        return InstagramProfile.objects.select_related("user").filter(
            user__username=username,
        ).order_by("-created_at", "id").first()
    return get_first_active_profile()


def cli_parser(description: str):
    """Bootstrap Django and return an ArgumentParser with ``--handle``.

    Call from ``if __name__ == "__main__"`` blocks. Sets up Django,
    configures logging, and returns a parser with ``--handle`` pre-added.
    After adding extra arguments, call ``cli_session(args)`` to get the session.
    """
    import argparse
    import os

    from linkedin.env_bootstrap import load_project_dotenv

    load_project_dotenv()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin.django_settings")

    import django
    django.setup()

    logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(message)s")
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--handle", default=None, help="Django username (default: first active profile)")
    return parser


def cli_session(args) -> "AccountSession":
    """Resolve profile from parsed args, create session, set default campaign."""
    instagram_profile = resolve_profile(args.handle)
    if not instagram_profile:
        print("No active InstagramProfile found.")
        raise SystemExit(1)

    session = get_or_create_session(instagram_profile)
    if not session.campaigns:
        print(f"No campaigns found for {instagram_profile}.")
        raise SystemExit(1)
    session.campaign = session.campaigns[0]
    return session
