# linkedin/api/messaging/conversations.py
"""Instagram DM conversation helpers (UI scrape)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def fetch_conversations(api, mailbox_urn: str = "", max_pages: int = 5) -> list[dict]:
    """Not used on Instagram hot path — inbox listing is thread-open based.

    Kept for import compatibility; returns empty list.
    """
    logger.debug("fetch_conversations is a no-op on Instagram (mailbox=%s)", mailbox_urn)
    return []


def fetch_messages(api, conversation_urn: str, max_pages: int = 5) -> list[dict]:
    """Fetch messages for a username / thread key via UI scrape."""
    from linkedin.actions.conversations import scrape_thread_messages

    username = (conversation_urn or "").replace("instagram:thread:", "").replace("instagram:", "").lstrip("@")
    if not username:
        return []
    session = api.session
    return scrape_thread_messages(session, username)
