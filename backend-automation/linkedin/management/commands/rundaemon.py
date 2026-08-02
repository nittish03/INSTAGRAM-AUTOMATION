import logging
import os
from pathlib import Path
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the Leadway daemon (onboard, validate, start task queue)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--onboard",
            metavar="CONFIG_JSON",
            help="Path to onboard config JSON (non-interactive mode).",
        )
        parser.add_argument(
            "--handle",
            metavar="USERNAME",
            default=None,
            help=(
                "Run only against this Django user's active LinkedIn profiles. "
                "Defaults to the first active profile globally (single-tenant mode)."
            ),
        )
        parser.add_argument(
            "--launcher-pid",
            metavar="PID",
            type=int,
            default=None,
            help="Deprecated compatibility option; daemon lifetime is explicit.",
        )

    def handle(self, *args, **options):
        self._configure_logging()
        self._print_version()
        self._ensure_playwright_browsers()
        self._ensure_db()
        self._ensure_onboarded(options["onboard"])
        session = self._create_session(handle=options.get("handle"))

        from linkedin.exceptions import AuthenticationError

        try:
            self._ensure_newsletter(session)
        except AuthenticationError as exc:
            logger.error("LinkedIn authentication failed: %s", exc)
            logger.error(
                "Tip: log in manually once on this machine, complete any "
                "security checkpoint, then re-run the daemon."
            )
            session.close()
            sys.exit(1)
        except RuntimeError as exc:
            # goto_page surfaces RuntimeError for unexpected URLs; treat unknown
            # navigation outcomes as auth failures rather than crashes.
            logger.error("Browser navigation failed during startup: %s", exc)
            session.close()
            sys.exit(1)

        import signal
        def graceful_exit(sig, frame):
            signal_name = getattr(signal.Signals(sig), "name", str(sig))
            logger.info(
                "Manual interrupt received (%s, pid=%s, ppid=%s). Closing session...",
                signal_name,
                os.getpid(),
                os.getppid(),
            )
            session.close()
            sys.exit(0)

        def ignore_sigterm(sig, frame):
            signal_name = getattr(signal.Signals(sig), "name", str(sig))
            logger.warning(
                "Ignoring %s (pid=%s, ppid=%s); daemon keeps running until manual stop.",
                signal_name,
                os.getpid(),
                os.getppid(),
            )

        signal.signal(signal.SIGINT, graceful_exit)
        signal.signal(signal.SIGTERM, ignore_sigterm)

        from linkedin.conf import (
            bot_active_hours_enabled,
            bot_sleep_enabled,
            bot_time_limits_enabled,
        )
        from linkedin.daemon import run_daemon
        logger.info(
            "Pacing: sleep=%s limits=%s active_hours=%s",
            bot_sleep_enabled(),
            bot_time_limits_enabled(),
            bot_active_hours_enabled(),
        )
        try:
            run_daemon(session)
        finally:
            session.close()

    # -- Steps ---------------------------------------------------------------

    def _print_version(self):
        sha = os.environ.get("GIT_SHA", "dev")
        logger.info("Leadway %s", sha[:8])

    def _configure_logging(self):
        # Windows console often defaults to cp1252, which cannot encode several
        # Unicode symbols used in logs. Prefer UTF-8 when the stream supports it.
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name, None)
            if stream and hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
        logging.getLogger().handlers.clear()
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        for name in (
            "urllib3", "httpx", "langchain", "openai", "playwright",
            "httpcore", "fastembed", "huggingface_hub", "filelock", "asyncio",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)

    def _ensure_playwright_browsers(self):
        """Fail fast when Playwright browser binaries are missing."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.error("Playwright import failed: %s", exc)
            logger.error("Install dependencies first: python -m pip install -r requirements/local.txt")
            sys.exit(1)

        try:
            with sync_playwright() as p:
                chromium_path = Path(p.chromium.executable_path)
            if not chromium_path.exists():
                logger.error("Playwright Chromium binary not found: %s", chromium_path)
                logger.error("Run this once in backend venv: playwright install chromium")
                sys.exit(1)
        except Exception as exc:
            logger.error("Playwright is not ready: %s", exc)
            logger.error("Run this once in backend venv: playwright install chromium")
            sys.exit(1)

    def _ensure_db(self):
        call_command("migrate", "--no-input")

        from linkedin.management.setup_crm import setup_crm
        setup_crm()

    def _ensure_onboarded(self, onboard_file):
        from linkedin.onboarding import (
            OnboardConfig, apply, collect_from_wizard, missing_keys,
        )

        if not missing_keys():
            return

        if onboard_file:
            apply(OnboardConfig.from_json(onboard_file))
        elif sys.stdin.isatty():
            apply(collect_from_wizard())
        else:
            missing = missing_keys()
            self.stderr.write(
                f"Onboarding incomplete and no TTY available.\n"
                f"Missing: {', '.join(sorted(missing))}\n"
                f"Pass --onboard <config.json> or run with an interactive terminal."
            )
            sys.exit(1)

    def _create_session(self, handle: str | None = None):
        from linkedin.browser.registry import get_first_active_profile, get_or_create_session
        from linkedin.conf import get_llm_site_config
        from linkedin.llm import validate_llm_site_config

        cfg = get_llm_site_config()
        ok, reason = validate_llm_site_config(cfg)
        if not ok:
            logger.error("LLM configuration invalid: %s", reason)
            sys.exit(1)

        profile = get_first_active_profile(handle=handle)
        if profile is None:
            if handle:
                logger.error(
                    "No active LinkedIn profiles found for user %r. "
                    "Open the LinkedIn Profiles page and add or activate one.",
                    handle,
                )
            else:
                logger.error("No active LinkedIn profiles found.")
            sys.exit(1)

        session = get_or_create_session(profile)

        if not session.campaigns:
            logger.error(
                "No campaigns linked to %s. Open the frontend Campaigns page, "
                "create or assign a campaign to this account, and re-run.",
                session.django_user.username,
            )
            sys.exit(1)
        campaign = next(
            (c for c in session.campaigns if not c.is_freemium), None,
        ) or session.campaigns[0]
        session.campaign = campaign

        return session

    def _ensure_newsletter(self, session):
        if session.linkedin_profile.newsletter_processed:
            return

        from linkedin.api.newsletter import ensure_newsletter_subscription
        from linkedin.setup.gdpr import apply_gdpr_newsletter_override
        from linkedin.url_utils import public_id_to_url

        profile = session.self_profile
        country_code = profile.get("country_code")
        apply_gdpr_newsletter_override(session, country_code)
        linkedin_url = public_id_to_url(profile["public_identifier"])
        ensure_newsletter_subscription(session, linkedin_url=linkedin_url)
        session.linkedin_profile.newsletter_processed = True
        session.linkedin_profile.save(update_fields=["newsletter_processed"])
