from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DraftRegenerationResult:
    draft_id: int
    public_id: str
    status: str
    old_content: str
    new_content: str
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.old_content != self.new_content


def regenerate_draft(draft, session, *, dry_run: bool = False) -> DraftRegenerationResult:
    """Regenerate one unapproved draft without approving or sending it.

    Existing draft text is excluded from the prompt history so the model does not
    treat an unsent draft as a prior LinkedIn message.
    """
    from crm.models import Deal, Lead
    from linkedin.agents.follow_up import run_follow_up_agent
    from linkedin.db.deals import get_profile_dict_for_public_id

    if not draft.is_draft or draft.is_approved:
        raise ValueError(f"ChatMessage {draft.pk} is not an unapproved draft")

    lead = draft.content_object
    if not isinstance(lead, Lead):
        raise ValueError(f"ChatMessage {draft.pk} is not attached to a Lead")

    campaign = draft.campaign
    if campaign is None:
        deals = list(Deal.objects.filter(lead=lead).select_related("campaign")[:2])
        if len(deals) > 1:
            raise ValueError(f"Draft {draft.pk} has ambiguous campaign context")
        campaign = deals[0].campaign if deals else None
    if campaign is None:
        raise ValueError(f"Draft {draft.pk} has no campaign context")

    old_content = draft.content or ""
    previous_campaign = getattr(session, "campaign", None)
    session.campaign = campaign
    try:
        profile_dict = get_profile_dict_for_public_id(session, lead.public_identifier)
        if profile_dict is None:
            raise ValueError(f"No Deal found for {lead.public_identifier} in campaign {campaign.pk}")

        profile = profile_dict.get("profile") or profile_dict
        decision = run_follow_up_agent(
            session,
            lead.public_identifier,
            profile,
            include_drafts=False,
        )
    finally:
        session.campaign = previous_campaign

    if decision.action != "send_message":
        reason = decision.reason or f"Agent chose {decision.action}"
        return DraftRegenerationResult(
            draft_id=draft.pk,
            public_id=lead.public_identifier,
            status=decision.action,
            old_content=old_content,
            new_content=old_content,
            reason=reason,
        )

    new_content = (decision.message or "").strip()
    if not new_content:
        raise ValueError(f"Agent returned an empty message for draft {draft.pk}")

    if not dry_run:
        updated = draft.__class__.objects.filter(
            pk=draft.pk,
            is_draft=True,
            is_approved=False,
            content=old_content,
        ).update(content=new_content)
        if not updated:
            return DraftRegenerationResult(
                draft_id=draft.pk,
                public_id=lead.public_identifier,
                status="stale",
                old_content=old_content,
                new_content=old_content,
                reason="Draft was approved, edited, sent, or deleted during regeneration.",
            )
        draft.content = new_content

    return DraftRegenerationResult(
        draft_id=draft.pk,
        public_id=lead.public_identifier,
        status="dry_run" if dry_run else "updated",
        old_content=old_content,
        new_content=new_content,
    )
