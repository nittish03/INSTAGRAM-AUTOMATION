# linkedin/api/voyager.py
"""Dead stubs — do not use for outreach.

Instagram enrichment lives in ``linkedin.api.client.PlaywrightInstagramAPI``.
Kept so accidental imports do not crash the app.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_connection_degree(data: Any) -> int | None:
    logger.debug("parse_connection_degree stub; always returns None")
    return None


def parse_linkedin_voyager_response(data: Any, public_identifier: str | None = None) -> dict | None:
    # Legacy symbol name; Instagram path does not use this.
    logger.debug("parse_linkedin_voyager_response stub; always returns None")
    return None
