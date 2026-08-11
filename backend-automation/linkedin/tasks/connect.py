# linkedin/tasks/connect.py
"""Outreach expansion task — discover/qualify, then queue HITL DM drafts.

Historically this task type was Instagram Follow. Product path is now DM-first:
find (or qualify) a lead, enqueue ``follow_up`` to create a draft, and never
require Follow / follow-back before messaging. The FOLLOW task type and ActionLog
bucket are retained for queue/rate-limit compatibility.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone
from termcolor import colored

from linkedin.conf import CAMPAIGN_CONFIG, bot_pacing_delay_seconds, bot_time_limits_enabled
from linkedin.models import ActionLog, Task
from linkedin.exceptions import TaskSkipped

logger = logging.getLogger(__name__)


def new_follows_paused() -> bool:
    """True when top-of-funnel outreach expansion is paused (legacy field name)."""
    from linkedin.models import SiteConfig

    return bool(getattr(SiteConfig.load(), "pause_new_follows", False))


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
    """Discover/qualify one lead and enqueue a HITL DM draft (no Follow)."""
    from crm.models import Deal

    cfg = CAMPAIGN_CONFIG
    campaign = session.campaign
    campaign_id = campaign.pk
    owner_id = getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(owner_id, int):
        owner_id = None
    instagram_profile_id = getattr(getattr(session, "instagram_profile", None), "pk", None)
    if not isinstance(instagram_profile_id, int):
        instagram_profile_id = None

    if new_follows_paused():
        raise TaskSkipped("New outreach expansion is paused.")

    strategy = strategy_for(campaign, qualifiers)

    # Expansion quota still uses the FOLLOW ActionLog bucket (legacy limits).
    if bot_time_limits_enabled() and not session.instagram_profile.can_execute(ActionLog.ActionType.FOLLOW):
        enqueue_connect(campaign_id, delay_seconds=_seconds_until_tomorrow())
        raise TaskSkipped("Daily/Weekly outreach expansion limit reached.")

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
    logger.info("[%s] %s", campaign, colored("\u25b6 outreach", "cyan", attrs=["bold"]))
    logger.info("[%s] %s (%s) — %s", campaign, public_id, stats, reason or "")

    if deal is None:
        logger.warning("outreach: no Deal for %s after find_candidate — rescheduling", public_id)
        _reschedule()
        return

    enqueue_follow_up(
        campaign_id,
        public_id,
        deal=deal,
        owner_id=owner_id,
        instagram_profile_id=instagram_profile_id,
    )

    name = f"{candidate.get('first_name', '')} {candidate.get('last_name', '')}".strip()
    if not name:
        name = candidate.get("name") or public_id
    session.instagram_profile.record_action(
        ActionLog.ActionType.FOLLOW,
        session.campaign,
        target_name=name,
        target_public_id=public_id,
        status="success",
        note="DM-first: queued HITL draft (no follow)",
    )

    _reschedule()


def _enqueue_task(
    *,
    task_type: str,
    payload: dict,
    delay_seconds: float,
    deal=None,
    dedup_keys: list[str] | None = None,
):
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
    if new_follows_paused():
        logger.info(
            "outreach enqueue skipped for campaign %s: new outreach expansion is paused",
            campaign_id,
        )
        return

    _enqueue_task(
        task_type=Task.TaskType.FOLLOW,
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
    instagram_profile_id: int | None = None,
):
    """Legacy follow-back poller — kept for dormant/manual paths; not used by DM-first outreach."""
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
    if instagram_profile_id is not None:
        payload["instagram_profile_id"] = instagram_profile_id
    dedup_keys = ["campaign_id", "public_id"]
    if owner_id is not None:
        dedup_keys.append("owner_id")
    if instagram_profile_id is not None:
        dedup_keys.append("instagram_profile_id")

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
    instagram_profile_id: int | None = None,
    *,
    apply_time_limits: bool = True,
):
    payload = {"campaign_id": campaign_id, "public_id": public_id}
    if owner_id is not None:
        payload["owner_id"] = owner_id
    if instagram_profile_id is not None:
        payload["instagram_profile_id"] = instagram_profile_id

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
    instagram_profile_id: int | None = None,
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
    if instagram_profile_id is not None:
        payload["instagram_profile_id"] = instagram_profile_id
    if sent_message_id is not None:
        payload["sent_message_id"] = sent_message_id
    dedup_keys = (
        ["campaign_id", "public_id", "sent_message_id"]
        if sent_message_id is not None
        else ["campaign_id", "public_id"]
    )
    if owner_id is not None:
        dedup_keys.append("owner_id")
    if instagram_profile_id is not None:
        dedup_keys.append("instagram_profile_id")

    _enqueue_task(
        task_type=Task.TaskType.REPLY_CHECK,
        payload=payload,
        delay_seconds=delay_seconds if delay_seconds is not None else interval,
        dedup_keys=dedup_keys,
        deal=deal,
    )
