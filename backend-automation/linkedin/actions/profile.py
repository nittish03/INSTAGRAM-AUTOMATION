# linkedin/actions/profile.py
"""Scrape an Instagram profile into the CRM enrichment shape."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from linkedin.conf import FIXTURE_PROFILES_DIR
from linkedin.api.client import PlaywrightInstagramAPI
from linkedin.url_utils import public_id_to_url

logger = logging.getLogger(__name__)


def scrape_profile(session, profile: dict):
    url = profile.get("url") or public_id_to_url(profile.get("public_identifier") or "")

    session.ensure_browser()
    session.wait()

    api = PlaywrightInstagramAPI(session=session)
    logger.info("Enriching Instagram profile → %s", url)
    enriched, data = api.get_profile(profile_url=url)
    if enriched:
        logger.info("Profile enriched – %s", enriched.get("public_identifier"))
    return enriched, data


def _save_profile_to_fixture(enriched_profile: Dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(enriched_profile, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Enriched profile saved to fixture → %s", path)


if __name__ == "__main__":
    from pprint import pprint
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Scrape an Instagram profile")
    parser.add_argument("--profile", default="me", help="Instagram username (default: me)")
    parser.add_argument("--save-fixture", action="store_true", help="Save raw data as test fixture")
    args = parser.parse_args()
    session = cli_session(args)

    test_profile = {"url": public_id_to_url(args.profile), "public_identifier": args.profile}
    print(f"Scraping profile as {session} → {args.profile}")
    profile, data = scrape_profile(session, test_profile)
    pprint(profile)
    if args.save_fixture and data is not None:
        _save_profile_to_fixture(data, FIXTURE_PROFILES_DIR / "instagram_profile.json")
