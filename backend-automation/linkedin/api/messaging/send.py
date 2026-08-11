# linkedin/api/messaging/send.py
"""Send Instagram DMs via Playwright UI."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def send_message(api, conversation_urn: str, message_text: str, mailbox_urn: str = "") -> dict:
    """Send a DM via Playwright UI.

    ``conversation_urn`` is treated as an Instagram username or
    ``instagram:thread:<username>`` / ``instagram:<username>`` key.
    ``api`` must expose ``.session`` (PlaywrightInstagramAPI).
    """
    from linkedin.actions.message import send_raw_message

    username = (conversation_urn or "").replace("instagram:thread:", "").replace("instagram:", "").lstrip("@")
    if not username or not (message_text or "").strip():
        raise ValueError("username and message_text are required")

    session = api.session
    profile = {"public_identifier": username, "url": f"https://www.instagram.com/{username}/"}
    ok = send_raw_message(session, profile, message_text.strip())
    if not ok:
        raise IOError(f"Instagram DM send failed for {username}")
    logger.info("Instagram DM delivered → %s", username)
    return {"ok": True, "username": username, "value": {"deliveredAt": None}}
