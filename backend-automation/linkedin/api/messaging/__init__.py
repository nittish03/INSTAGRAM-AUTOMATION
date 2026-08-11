# linkedin/api/messaging/__init__.py
"""Instagram messaging helpers (Playwright UI)."""
from linkedin.api.messaging.conversations import fetch_conversations, fetch_messages
from linkedin.api.messaging.send import send_message

# Back-compat alias used by older call sites / tests
send_message_api = send_message

__all__ = ["fetch_conversations", "fetch_messages", "send_message", "send_message_api"]
