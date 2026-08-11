# linkedin/actions/conversations.py
"""Sync Instagram DM threads via Playwright UI."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from linkedin.actions.message import open_inbox
from linkedin.actions.search import _go_to_profile
from linkedin.url_utils import public_id_to_url

logger = logging.getLogger(__name__)


def _stable_message_id(username: str, text: str, idx: int) -> str:
    digest = hashlib.sha1(f"{username}|{idx}|{text}".encode("utf-8")).hexdigest()[:24]
    return f"ig_{username}_{digest}"


def _open_thread_with_user(session, username: str) -> bool:
    """Open DM thread for username via profile Message button or inbox search."""
    page = session.page
    username = username.lstrip("@")

    # Prefer profile → Message (creates/opens thread)
    try:
        _go_to_profile(session, public_id_to_url(username), username)
        session.wait()
        for sel in (
            'header button:has-text("Message"):visible',
            'main button:has-text("Message"):visible',
            'div[role="button"]:has-text("Message"):visible',
        ):
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click()
                session.wait(2, 4)
                return "/direct/" in (page.url or "")
    except Exception as exc:
        logger.debug("Profile→Message open failed for %s: %s", username, exc)

    # Inbox search fallback
    try:
        open_inbox(session)
        session.wait()
        # New message / search
        for label in ("New message", "Search", "To:"):
            try:
                el = page.get_by_text(label, exact=False).first
                if el.count() > 0:
                    el.click(timeout=2000)
                    session.wait()
                    break
            except Exception:
                continue
        search = page.locator('input[placeholder*="Search" i], input[name="queryBox"], input[type="text"]').first
        if search.count() > 0:
            search.fill(username)
            session.wait(1, 2)
            result = page.locator(f'text=/{re.escape(username)}/i').first
            if result.count() > 0:
                result.click()
                session.wait()
                # Chat / Next
                for btn_label in ("Chat", "Next", "Message"):
                    try:
                        b = page.get_by_role("button", name=btn_label)
                        if b.count() > 0:
                            b.first.click(timeout=2000)
                            session.wait()
                            break
                    except Exception:
                        continue
                return True
    except Exception as exc:
        logger.debug("Inbox search open failed for %s: %s", username, exc)
    return False


def scrape_thread_messages(session, username: str) -> list[dict]:
    """Return parsed messages from the open / opened DM thread.

    Each item: {entityUrn, text, sender_name, sender_host_urn, delivered_at, is_outgoing}
    """
    page = session.page
    username = username.lstrip("@")
    self_username = ""
    try:
        self_username = (session.self_profile.get("username")
                         or session.self_profile.get("public_identifier")
                         or session.instagram_profile.instagram_username
                         or "").lstrip("@")
    except Exception:
        self_username = (getattr(session.instagram_profile, "instagram_username", "") or "").lstrip("@")

    if not _open_thread_with_user(session, username):
        logger.debug("No DM thread for %s", username)
        return []

    session.wait(1, 2)
    # TODO: Instagram thread DOM is highly variable; collect text bubbles best-effort.
    bubbles = page.locator(
        'div[role="listbox"] div[dir="auto"], '
        'div[role="row"] div[dir="auto"], '
        'div[class*="message"] div[dir="auto"]'
    )
    texts: list[str] = []
    try:
        count = min(bubbles.count(), 80)
        for i in range(count):
            txt = (bubbles.nth(i).inner_text() or "").strip()
            if txt:
                texts.append(txt)
    except Exception as exc:
        logger.debug("Bubble scrape failed: %s", exc)

    # Heuristic outgoing: we can't reliably get sender from DOM — alternate is unsafe.
    # Prefer marking unknown as incoming unless bubble is near our composer (last few).
    # For HITL sync, store texts with synthetic ids; is_outgoing inferred weakly.
    messages: list[dict] = []
    for idx, text in enumerate(texts):
        # Without reliable attribution, treat all scraped as incoming unless already known
        # outgoing placeholders match by content in db/chat.py.
        messages.append(
            {
                "entityUrn": _stable_message_id(username, text, idx),
                "text": text,
                "sender_name": username,
                "sender_host_urn": f"instagram:{username}",
                "delivered_at": None,
                "is_outgoing": False,
            }
        )
    logger.debug("Scraped %d DM texts for %s (self=%s)", len(messages), username, self_username)
    return messages


def find_conversation_urn(api, target_urn: str, mailbox_urn: str) -> str | None:
    """Deprecated helper — Instagram uses usernames, not conversation URNs."""
    return None


def find_conversation_urn_via_navigation(session, target_urn: str) -> str | None:
    """Deprecated — kept so imports do not break; returns synthetic thread key."""
    username = (target_urn or "").replace("instagram:", "").lstrip("@")
    if not username:
        return None
    if _open_thread_with_user(session, username):
        return f"instagram:thread:{username}"
    return None


def parse_message_element(msg: dict) -> dict | None:
    """Normalize a scraped / legacy message dict."""
    if not isinstance(msg, dict):
        return None
    text = msg.get("text") or ""
    if not text and isinstance(msg.get("body"), dict):
        text = msg["body"].get("text", "")
    if not text:
        return None
    delivered_at = msg.get("delivered_at")
    if isinstance(delivered_at, (int, float)):
        delivered_at = datetime.fromtimestamp(delivered_at / 1000, tz=timezone.utc)
    return {
        "entityUrn": msg.get("entityUrn") or msg.get("instagram_message_id") or "",
        "text": text,
        "sender_name": msg.get("sender_name") or "unknown",
        "sender_host_urn": msg.get("sender_host_urn") or "",
        "delivered_at": delivered_at,
        "is_outgoing": bool(msg.get("is_outgoing", False)),
    }


def parse_messages(elements: list[dict]) -> list[dict]:
    out = []
    for msg in elements or []:
        parsed = parse_message_element(msg)
        if not parsed:
            continue
        ts = parsed["delivered_at"]
        out.append(
            {
                "sender": parsed["sender_name"],
                "text": parsed["text"],
                "timestamp": ts.strftime("%Y-%m-%d %H:%M") if ts else "",
            }
        )
    return out


def get_conversation(session, target_urn: str, mailbox_urn: str = "") -> list[dict] | None:
    username = (target_urn or "").replace("instagram:", "").lstrip("@")
    elements = scrape_thread_messages(session, username)
    if not elements:
        return None
    return parse_messages(elements)
