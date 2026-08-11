import sys

from django.core.management.base import BaseCommand

from linkedin.conf import (
    DEFAULT_FOLLOW_DAILY_LIMIT,
    DEFAULT_FOLLOW_WEEKLY_LIMIT,
    DEFAULT_FOLLOW_UP_DAILY_LIMIT,
)


class Command(BaseCommand):
    help = "Run onboarding (interactive or non-interactive with CLI flags or --config-file)."

    def add_arguments(self, parser):
        parser.add_argument("--non-interactive", action="store_true")
        parser.add_argument(
            "--config-file",
            help="JSON file with onboard config (avoids shell-escaping issues).",
        )
        # Individual flags (used when --config-file is not provided)
        parser.add_argument("--instagram-username", default="")
        parser.add_argument("--instagram-password", default="")
        parser.add_argument("--campaign-name", default="")
        parser.add_argument("--product-description", default="")
        parser.add_argument("--campaign-objective", default="")
        parser.add_argument("--booking-link", default="")
        parser.add_argument("--seed-urls", default="")
        parser.add_argument("--llm-api-key", default="")
        parser.add_argument("--llm-provider", default="openai")
        parser.add_argument("--ai-model", default="")
        parser.add_argument("--llm-api-base", default="")
        parser.add_argument("--azure-deployment", default="")
        parser.add_argument("--azure-api-version", default="2024-10-21")
        parser.add_argument("--newsletter", action="store_true", default=True)
        parser.add_argument("--no-newsletter", dest="newsletter", action="store_false")
        parser.add_argument("--follow-daily-limit", type=int, default=DEFAULT_FOLLOW_DAILY_LIMIT)
        parser.add_argument("--follow-weekly-limit", type=int, default=DEFAULT_FOLLOW_WEEKLY_LIMIT)
        parser.add_argument("--follow-up-daily-limit", type=int, default=DEFAULT_FOLLOW_UP_DAILY_LIMIT)

    def handle(self, *args, **options):
        from linkedin.onboarding import (
            OnboardConfig, apply, collect_from_wizard, missing_keys,
        )

        if not options["non_interactive"]:
            if not sys.stdin.isatty():
                self.stderr.write(
                    "No TTY available. Use --non-interactive with --config-file or flags."
                )
                sys.exit(1)
            if not missing_keys():
                return
            config = collect_from_wizard()
            apply(config)
            return

        if options["config_file"]:
            config = OnboardConfig.from_json(options["config_file"])
        else:
            config = OnboardConfig(
                instagram_username=options["instagram_username"],
                instagram_password=options["instagram_password"],
                campaign_name=options["campaign_name"],
                product_description=options["product_description"],
                campaign_objective=options["campaign_objective"],
                booking_link=options["booking_link"],
                seed_urls=options["seed_urls"],
                llm_api_key=options["llm_api_key"],
                llm_provider=options["llm_provider"],
                ai_model=options["ai_model"],
                llm_api_base=options["llm_api_base"],
                azure_deployment=options["azure_deployment"],
                azure_api_version=options["azure_api_version"],
                newsletter=options["newsletter"],
                follow_daily_limit=options["follow_daily_limit"],
                follow_weekly_limit=options["follow_weekly_limit"],
                follow_up_daily_limit=options["follow_up_daily_limit"],
            )

        if not config.instagram_username:
            self.stderr.write("instagram_username is required in non-interactive mode")
            sys.exit(1)
        if not config.instagram_password:
            self.stderr.write("instagram_password is required in non-interactive mode")
            sys.exit(1)

        apply(config)
