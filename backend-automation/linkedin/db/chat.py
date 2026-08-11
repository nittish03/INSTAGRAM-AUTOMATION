"""Upsert Instagram DM history into ChatMessage (UI scrape)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_lead_and_ct(public_identifier: str):
    """Return (lead, content_type) for a public identifier."""
    from django.contrib.contenttypes.models import ContentType
    from crm.models import Lead

    lead = Lead.objects.filter(public_identifier=public_identifier).first()
    if lead is None:
        raise ValueError(f"No Lead found for public_identifier={public_identifier!r}")

    ct = ContentType.objects.get_for_model(lead)
    return lead, ct


def sync_conversation(session, public_identifier: str, *, include_drafts: bool = False) -> list[dict]:
    """Fetch Instagram DMs via UI and upsert into ChatMessage.

    Returns messages as a list of {sender, text, timestamp, is_outgoing} dicts
    from the DB (always the source of truth after sync).
    """
    lead, ct = _get_lead_and_ct(public_identifier)
    _sync_from_instagram(session, public_identifier, lead, ct)

    return _read_from_db(
        lead,
        ct,
        owner=session.django_user,
        instagram_profile=getattr(session, "instagram_profile", None),
        include_drafts=include_drafts,
    )


def _sync_from_instagram(session, public_identifier: str, lead, ct):
    """Scrape DM thread and upsert into DB."""
    from chat.models import ChatMessage
    from linkedin.actions.conversations import parse_message_element, scrape_thread_messages

    session.ensure_browser()
    campaign = getattr(session, "campaign", None)
    if not isinstance(getattr(campaign, "pk", None), int):
        campaign = None
    instagram_profile = getattr(session, "instagram_profile", None)
    if not isinstance(getattr(instagram_profile, "pk", None), int):
        instagram_profile = None

    username = (public_identifier or "").lstrip("@")
    elements = scrape_thread_messages(session, username)
    if not elements:
        logger.debug("sync: no Instagram DM thread for %s", public_identifier)
        return

    self_username = ""
    try:
        self_username = (
            session.self_profile.get("username")
            or session.self_profile.get("public_identifier")
            or ""
        ).lstrip("@")
    except Exception:
        self_username = (getattr(session.instagram_profile, "instagram_username", "") or "").lstrip("@")

    for msg in elements:
        parsed = parse_message_element(msg)
        if not parsed or not parsed["entityUrn"]:
            continue

        is_outgoing = bool(parsed.get("is_outgoing"))
        # Match local sent placeholders by identical content
        if not is_outgoing:
            placeholder = ChatMessage.objects.filter(
                content_type=ct,
                object_id=lead.pk,
                owner=session.django_user,
                instagram_profile=instagram_profile,
                is_outgoing=True,
                instagram_message_id__startswith="sent_",
                content=parsed["text"],
            ).order_by("-creation_date").first()
            if placeholder and not ChatMessage.objects.filter(
                instagram_message_id=parsed["entityUrn"]
            ).exists():
                # Content matched an outgoing we already sent — treat as ours
                placeholder.instagram_message_id = parsed["entityUrn"]
                if parsed["delivered_at"]:
                    placeholder.creation_date = parsed["delivered_at"]
                placeholder.is_draft = False
                placeholder.save(update_fields=["instagram_message_id", "creation_date", "is_draft"])
                logger.debug("sync: matched local sent placeholder for %s", public_identifier)
                continue

        # If sender_host_urn matches self, mark outgoing
        host = (parsed.get("sender_host_urn") or "").replace("instagram:", "").lstrip("@")
        if self_username and host and host.lower() == self_username.lower():
            is_outgoing = True

        _, created = ChatMessage.objects.update_or_create(
            instagram_message_id=parsed["entityUrn"],
            defaults={
                "content_type": ct,
                "object_id": lead.pk,
                "content": parsed["text"],
                "is_outgoing": is_outgoing,
                "owner": session.django_user,
                "instagram_profile": instagram_profile,
                "campaign": campaign,
                **({"creation_date": parsed["delivered_at"]} if parsed["delivered_at"] else {}),
            },
        )
        if created:
            logger.debug("sync: new message for %s", public_identifier)

    logger.debug("sync: processed %d Instagram messages for %s", len(elements), public_identifier)


def _read_from_db(lead, ct, *, owner, instagram_profile=None, include_drafts: bool = True) -> list[dict]:
    """Read all ChatMessages for a lead, sorted chronologically."""
    from chat.models import ChatMessage

    lead_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "them"

    messages = ChatMessage.objects.filter(
        content_type=ct,
        object_id=lead.pk,
        owner=owner,
    ).select_related("owner").order_by("creation_date")
    if instagram_profile is not None:
        messages = messages.filter(instagram_profile=instagram_profile)
    if not include_drafts:
        messages = messages.filter(is_draft=False).exclude(instagram_message_id__startswith="draft_")

    real_outgoing_texts = set(
        messages.filter(is_outgoing=True)
        .exclude(instagram_message_id__startswith="sent_")
        .exclude(instagram_message_id__startswith="draft_")
        .values_list("content", flat=True)
    )

    result = []
    for msg in messages:
        if not msg.content:
            continue
        if msg.instagram_message_id.startswith("sent_") and msg.is_outgoing and msg.content in real_outgoing_texts:
            continue
        if msg.is_outgoing:
            msg_owner = msg.owner
            sender = (
                f"{msg_owner.first_name or ''} {msg_owner.last_name or ''}".strip()
                if msg_owner
                else "me"
            )
        else:
            sender = lead_name
        result.append(
            {
                "sender": sender or "me",
                "text": msg.content,
                "timestamp": msg.creation_date.strftime("%Y-%m-%d %H:%M") if msg.creation_date else "",
                "timestamp_dt": msg.creation_date,
                "is_outgoing": msg.is_outgoing,
            }
        )
    return result
