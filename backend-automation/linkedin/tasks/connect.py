# linkedin/tasks/connect.py
"""Connect task — pulls one candidate, connects, self-reschedules.

Works for both regular and freemium campaigns via ConnectStrategy.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone
from termcolor import colored

from linkedin.conf import CAMPAIGN_CONFIG, bot_pacing_delay_seconds, bot_time_limits_enabled
from linkedin.db.deals import increment_connect_attempts, set_profile_state
from linkedin.db.leads import disqualify_lead
from linkedin.models import ActionLog, Task
from linkedin.enums import ProfileState
from linkedin.exceptions import ReachedConnectionLimit, SkipProfile, TaskSkipped

logger = logging.getLogger(__name__)

MAX_CONNECT_ATTEMPTS = 3


def new_connection_invites_paused() -> bool:
    from linkedin.models import SiteConfig

    return bool(getattr(SiteConfig.load(), "pause_new_connection_invites", False))


@dataclass
class ConnectStrategy:
    find_candidate: Callable
    pre_connect: Callable | None
    delay: float
    action_fraction: float  # 1.0 = always fire at base delay
    qualifier: object

    def compute_delay(self, elapsed: float) -> float:
        """Delay until next connect, scaled by elapsed execution time for freemium campaigns."""
        if not bot_time_limits_enabled():
            return 0.0
        if self.action_fraction >= 1.0:
            return self.delay
        return max(self.delay, elapsed * (1 - self.action_fraction) / self.action_fraction)


def strategy_for(campaign, qualifiers):
    """Build the right ConnectStrategy based on campaign type."""
    qualifier = qualifiers.get(campaign.pk)

    if campaign.is_freemium:
        from linkedin.db.deals import create_freemium_deal
        from linkedin.pipeline.freemium_pool import find_freemium_candidate

        fraction = campaign.action_fraction
        return ConnectStrategy(
            find_candidate=lambda s: find_freemium_candidate(s, qualifier),
            pre_connect=lambda s, pid: create_freemium_deal(s, pid),
            delay=CAMPAIGN_CONFIG["connect_delay_seconds"],
            action_fraction=fraction,
            qualifier=qualifier,
        )

    from linkedin.pipeline.pools import find_candidate

    return ConnectStrategy(
        find_candidate=lambda s: find_candidate(s, qualifier),
        pre_connect=None,
        delay=CAMPAIGN_CONFIG["connect_delay_seconds"],
        action_fraction=1.0,
        qualifier=qualifier,
    )


def _seconds_until_tomorrow() -> float:
    from django.utils import timezone
    import datetime

    now = timezone.now()
    tomorrow = (now + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return (tomorrow - now).total_seconds()


def handle_connect(task, session, qualifiers):
    from linkedin.actions.connect import send_connection_request
    from linkedin.actions.status import get_connection_assessment
    from linkedin.models import OutreachEvent
    from linkedin.outreach_tracking import emit_outreach_event, update_deal_inference
    from crm.models import Deal

    cfg = CAMPAIGN_CONFIG
    campaign = session.campaign
    campaign_id = campaign.pk
    owner_id = getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(owner_id, int):
        owner_id = None
    linkedin_profile_id = getattr(getattr(session, "linkedin_profile", None), "pk", None)
    if not isinstance(linkedin_profile_id, int):
        linkedin_profile_id = None

    if new_connection_invites_paused():
        raise TaskSkipped("New connection invite expansion is paused.")

    strategy = strategy_for(campaign, qualifiers)

    # --- FIRST: rate limit check (cheapest gate) ---
    if bot_time_limits_enabled() and not session.linkedin_profile.can_execute(ActionLog.ActionType.CONNECT):
        enqueue_connect(campaign_id, delay_seconds=_seconds_until_tomorrow())
        raise TaskSkipped("Daily/Weekly connection limit reached.")

    # --- THEN: find candidate ---
    candidate = strategy.find_candidate(session)
    if candidate is None:
        enqueue_connect(
            campaign_id,
            delay_seconds=cfg["connect_no_candidate_delay_seconds"],
            apply_time_limits=False,
        )
        return

    public_id = candidate.get("public_identifier") or candidate.get("public_id")
    if not public_id:
        raise TaskSkipped("Candidate missing public identifier.")
    profile = candidate.get("profile") or candidate

    # Freemium campaigns need a Deal before set_profile_state
    deal = None
    if strategy.pre_connect:
        deal = strategy.pre_connect(session, public_id)

    if deal is None:
        deal = Deal.objects.filter(
            lead__public_identifier=public_id,
            campaign=session.campaign,
        ).first()

    def _reschedule():
        elapsed = (timezone.now() - task.started_at).total_seconds() if task.started_at else 0
        enqueue_connect(campaign_id, delay_seconds=strategy.compute_delay(elapsed), deal=deal)

    reason = deal.reason if deal else ""
    stats = strategy.qualifier.explain(candidate, session) if strategy.qualifier else ""
    logger.info("[%s] %s", campaign, colored("\u25b6 connect", "cyan", attrs=["bold"]))
    logger.info("[%s] %s (%s) — %s", campaign, public_id, stats, reason or "")

    try:
        assessment = get_connection_assessment(session, profile)

        verified_connected = (
            assessment.state == ProfileState.CONNECTED
            and assessment.source == "api_degree_1"
        )
        if verified_connected:
            if deal:
                update_deal_inference(deal, assessment.source, assessment.confidence)
            emit_outreach_event(
                OutreachEvent.EventType.CONNECTION_DETECTED,
                deal=deal,
                lead=deal.lead if deal else None,
                campaign=session.campaign,
                public_id=public_id,
                metadata={
                    "source": assessment.source,
                    "confidence": assessment.confidence,
                    "via": "pre_connect_status_check",
                },
            )
            set_profile_state(session, public_id, assessment.state.value)
            if deal and deal.lead_id:
                from google_integration.sheet_sync import sync_lead_to_google_sheet

                sync_lead_to_google_sheet(deal.lead, config_user=owner_id)
            enqueue_follow_up(
                campaign_id,
                public_id,
                deal=deal,
                owner_id=owner_id,
                linkedin_profile_id=linkedin_profile_id,
            )
            _reschedule()
            return

        if assessment.state in (ProfileState.PENDING, ProfileState.CONNECTED):
            if assessment.state == ProfileState.CONNECTED:
                logger.info(
                    "%s looked connected via %s but is not API degree-1 yet — keeping Pending",
                    public_id,
                    assessment.source,
                )
                if deal:
                    update_deal_inference(deal, assessment.source, assessment.confidence)
            set_profile_state(session, public_id, ProfileState.PENDING.value)
            if deal and deal.lead_id:
                from google_integration.sheet_sync import sync_pending_lead_to_google_sheet

                sync_pending_lead_to_google_sheet(
                    deal.lead,
                    reason_code="pre_connect_pending_detected",
                    config_user=owner_id,
                )
            enqueue_check_pending(
                campaign_id, public_id,
                backoff_hours=cfg["check_pending_recheck_after_hours"],
                deal=deal,
                owner_id=owner_id,
                linkedin_profile_id=linkedin_profile_id,
            )
            _reschedule()
            return

        # Profile page already loaded — attempt invite
        new_state = send_connection_request(session=session, profile=profile)

        if new_state == ProfileState.QUALIFIED:
            # No Connect button found — track attempt, disqualify after MAX_CONNECT_ATTEMPTS
            attempts = increment_connect_attempts(session, public_id)
            if attempts >= MAX_CONNECT_ATTEMPTS:
                reason = f"Unreachable: no Connect button after {attempts} attempts"
                disqualify_lead(public_id)
                emit_outreach_event(
                    OutreachEvent.EventType.INVITE_FAILED,
                    deal=deal,
                    lead=deal.lead if deal else None,
                    campaign=session.campaign,
                    public_id=public_id,
                    metadata={"reason": "no_connect_button_max_attempts", "attempts": attempts},
                )
                set_profile_state(session, public_id, ProfileState.FAILED.value, reason=reason)
                logger.warning("Disqualified %s — %s", public_id, reason)
            else:
                emit_outreach_event(
                    OutreachEvent.EventType.INVITE_FAILED,
                    deal=deal,
                    lead=deal.lead if deal else None,
                    campaign=session.campaign,
                    public_id=public_id,
                    metadata={"reason": "no_connect_button", "attempt": attempts},
                )
                set_profile_state(session, public_id, new_state.value)
                if deal and deal.lead_id:
                    from google_integration.sheet_sync import sync_qualified_lead_to_google_sheet

                    sync_qualified_lead_to_google_sheet(
                        deal.lead,
                        reason_code="connect_no_button",
                        config_user=owner_id,
                    )
                logger.debug("%s: connect attempt %d/%d — no button found", public_id, attempts, MAX_CONNECT_ATTEMPTS)
        else:
            if new_state == ProfileState.PENDING and deal:
                emit_outreach_event(
                    OutreachEvent.EventType.INVITE_SENT,
                    deal=deal,
                    lead=deal.lead,
                    campaign=session.campaign,
                    public_id=public_id,
                    metadata={"via": "send_connection_request"},
                )
            verified_post_connect = False
            if new_state == ProfileState.CONNECTED and deal:
                post = get_connection_assessment(session, profile)
                verified_post_connect = (
                    post.state == ProfileState.CONNECTED
                    and post.source == "api_degree_1"
                )
                update_deal_inference(deal, post.source, post.confidence)
                if verified_post_connect:
                    emit_outreach_event(
                        OutreachEvent.EventType.CONNECTION_DETECTED,
                        deal=deal,
                        lead=deal.lead,
                        campaign=session.campaign,
                        public_id=public_id,
                        metadata={
                            "source": post.source,
                            "confidence": post.confidence,
                            "via": "post_connect_send",
                        },
                    )
                else:
                    logger.info(
                        "%s connect result looked connected via %s but is not API degree-1 yet — keeping Pending",
                        public_id,
                        post.source,
                    )

            state_to_store = (
                ProfileState.CONNECTED
                if new_state == ProfileState.CONNECTED and verified_post_connect
                else new_state
            )
            if new_state == ProfileState.CONNECTED and not verified_post_connect:
                state_to_store = ProfileState.PENDING

            set_profile_state(session, public_id, state_to_store.value)
            if state_to_store == ProfileState.CONNECTED and deal and deal.lead_id:
                from google_integration.sheet_sync import sync_lead_to_google_sheet

                sync_lead_to_google_sheet(deal.lead, config_user=owner_id)
            if state_to_store == ProfileState.PENDING and deal and deal.lead_id:
                from google_integration.sheet_sync import sync_pending_lead_to_google_sheet

                sync_pending_lead_to_google_sheet(
                    deal.lead,
                    reason_code="invite_sent",
                    config_user=owner_id,
                )
            name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip() or public_id
            session.linkedin_profile.record_action(
                ActionLog.ActionType.CONNECT,
                session.campaign,
                target_name=name,
                target_public_id=public_id,
                status="success" if state_to_store in (ProfileState.PENDING, ProfileState.CONNECTED) else "failed"
            )
            if state_to_store not in (ProfileState.PENDING, ProfileState.CONNECTED):
                emit_outreach_event(
                    OutreachEvent.EventType.INVITE_FAILED,
                    deal=deal,
                    lead=deal.lead if deal else None,
                    campaign=session.campaign,
                    public_id=public_id,
                    metadata={"reason": "connect_action_unsuccessful", "state": new_state.value},
                )

            if state_to_store == ProfileState.PENDING:
                enqueue_check_pending(
                    campaign_id, public_id,
                    backoff_hours=cfg["check_pending_recheck_after_hours"],
                    deal=deal,
                    owner_id=owner_id,
                    linkedin_profile_id=linkedin_profile_id,
                )
            elif state_to_store == ProfileState.CONNECTED:
                enqueue_follow_up(
                    campaign_id,
                    public_id,
                    deal=deal,
                    owner_id=owner_id,
                    linkedin_profile_id=linkedin_profile_id,
                )

    except ReachedConnectionLimit as e:
        logger.warning("Rate limited: %s", e)
        session.linkedin_profile.mark_exhausted(ActionLog.ActionType.CONNECT)
        enqueue_connect(
            campaign_id,
            delay_seconds=_seconds_until_tomorrow(),
            deal=deal,
            apply_time_limits=False,
        )
        raise TaskSkipped(f"Connection limit: {e}")
    except SkipProfile as e:
        logger.warning("Skipping %s: %s", public_id, e)
        set_profile_state(session, public_id, ProfileState.FAILED.value)

    _reschedule()


# ------------------------------------------------------------------
# Enqueue helpers (used by all task types)
# ------------------------------------------------------------------

def _enqueue_task(task_type, payload, delay_seconds=10, dedup_keys=None, deal=None):
    """Generic task creator with payload-based deduplication."""
    from linkedin.models import Task
    from datetime import timedelta

    filter_kwargs = {
        "task_type": task_type,
        "status": Task.Status.PENDING,
    }
    for key in (dedup_keys if dedup_keys is not None else payload):
        filter_kwargs[f"payload__{key}"] = payload[key]

    if not Task.objects.filter(**filter_kwargs).exists():
        Task.objects.create(
            task_type=task_type,
            scheduled_at=timezone.now() + timedelta(seconds=delay_seconds),
            payload=payload,
            deal=deal,
        )


def enqueue_connect(
    campaign_id: int,
    delay_seconds: float = 10,
    deal=None,
    *,
    apply_time_limits: bool = True,
):
    if new_connection_invites_paused():
        logger.info("connect enqueue skipped for campaign %s: new connection invite expansion is paused", campaign_id)
        return

    _enqueue_task(
        task_type=Task.TaskType.CONNECT,
        payload={"campaign_id": campaign_id},
        delay_seconds=bot_pacing_delay_seconds(delay_seconds) if apply_time_limits else delay_seconds,
        deal=deal,
    )


def enqueue_check_pending(
    campaign_id: int,
    public_id: str,
    backoff_hours: float,
    deal=None,
    owner_id: int | None = None,
    linkedin_profile_id: int | None = None,
):
    # Equal-jitter backoff: uniform spread across [half, backoff]
    half = backoff_hours / 2
    delay_hours = half + random.uniform(0, half)
    payload = {
        "campaign_id": campaign_id,
        "public_id": public_id,
        "backoff_hours": backoff_hours,
    }
    if owner_id is not None:
        payload["owner_id"] = owner_id
    if linkedin_profile_id is not None:
        payload["linkedin_profile_id"] = linkedin_profile_id
    dedup_keys = ["campaign_id", "public_id"]
    if owner_id is not None:
        dedup_keys.append("owner_id")
    if linkedin_profile_id is not None:
        dedup_keys.append("linkedin_profile_id")

    _enqueue_task(
        task_type=Task.TaskType.CHECK_PENDING,
        payload=payload,
        delay_seconds=delay_hours * 3600,
        dedup_keys=dedup_keys,
        deal=deal,
    )
    return delay_hours


def enqueue_follow_up(
    campaign_id: int,
    public_id: str,
    delay_seconds: float = 10,
    deal=None,
    owner_id: int | None = None,
    linkedin_profile_id: int | None = None,
    *,
    apply_time_limits: bool = True,
):
    payload = {"campaign_id": campaign_id, "public_id": public_id}
    if owner_id is not None:
        payload["owner_id"] = owner_id
    if linkedin_profile_id is not None:
        payload["linkedin_profile_id"] = linkedin_profile_id

    _enqueue_task(
        task_type=Task.TaskType.FOLLOW_UP,
        payload=payload,
        delay_seconds=bot_pacing_delay_seconds(delay_seconds) if apply_time_limits else delay_seconds,
        deal=deal,
    )


def enqueue_reply_check(
    campaign_id: int,
    public_id: str,
    *,
    sent_message_id: int | None = None,
    sent_at=None,
    attempt: int = 1,
    interval_seconds: float | None = None,
    max_attempts: int | None = None,
    window_seconds: float | None = None,
    delay_seconds: float | None = None,
    deal=None,
    owner_id: int | None = None,
    linkedin_profile_id: int | None = None,
):
    from datetime import timedelta

    cfg = CAMPAIGN_CONFIG
    interval = interval_seconds or cfg["reply_check_interval_seconds"]
    max_checks = max_attempts or cfg["reply_check_max_attempts"]
    window = window_seconds or cfg["reply_check_window_seconds"]
    anchor = sent_at or timezone.now()
    payload = {
        "campaign_id": campaign_id,
        "public_id": public_id,
        "sent_at": anchor.isoformat(),
        "attempt": attempt,
        "max_attempts": max_checks,
        "interval_seconds": interval,
        "expires_at": (anchor + timedelta(seconds=window)).isoformat(),
    }
    if owner_id is not None:
        payload["owner_id"] = owner_id
    if linkedin_profile_id is not None:
        payload["linkedin_profile_id"] = linkedin_profile_id
    if sent_message_id is not None:
        payload["sent_message_id"] = sent_message_id
    dedup_keys = ["campaign_id", "public_id", "sent_message_id"] if sent_message_id is not None else ["campaign_id", "public_id"]
    if owner_id is not None:
        dedup_keys.append("owner_id")
    if linkedin_profile_id is not None:
        dedup_keys.append("linkedin_profile_id")

    _enqueue_task(
        task_type=Task.TaskType.REPLY_CHECK,
        payload=payload,
        delay_seconds=delay_seconds if delay_seconds is not None else interval,
        dedup_keys=dedup_keys,
        deal=deal,
    )
