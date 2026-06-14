# linkedin/daemon.py
from __future__ import annotations

import logging
import random
import time
import traceback
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import close_old_connections, connections
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone
from termcolor import colored

from linkedin.exceptions import TaskSkipped

from linkedin.conf import (
    ACTIVE_END_HOUR,
    ACTIVE_START_HOUR,
    ACTIVE_TIMEZONE,
    CAMPAIGN_CONFIG,
    ENABLE_ACTIVE_HOURS,
    REST_DAYS,
    bot_delay_seconds,
    bot_time_limits_enabled,
)
from linkedin.diagnostics import failure_diagnostics
from linkedin.ml.qualifier import BayesianQualifier, KitQualifier
from linkedin.models import Task
from linkedin.tasks.check_pending import handle_check_pending
from linkedin.tasks.connect import (
    enqueue_check_pending,
    enqueue_connect,
    enqueue_follow_up,
    handle_connect,
    new_connection_invites_paused,
)
from linkedin.tasks.follow_up import handle_follow_up
from linkedin.tasks.reply_check import handle_reply_check
from linkedin.tasks.send_message import handle_send_message

logger = logging.getLogger(__name__)

# Keep the daemon responsive without spinning CPU or hammering the database.
_IDLE_POLL_INTERVAL_SECONDS = 15.0
_OWNER_SCOPED_TASK_TYPES = {
    Task.TaskType.CHECK_PENDING,
    Task.TaskType.FOLLOW_UP,
    Task.TaskType.SEND_MESSAGE,
    Task.TaskType.REPLY_CHECK,
}
_OUTREACH_TASK_TYPES = {
    Task.TaskType.CONNECT,
    Task.TaskType.SEND_MESSAGE,
}

_HANDLERS = {
    Task.TaskType.CONNECT: handle_connect,
    Task.TaskType.CHECK_PENDING: handle_check_pending,
    Task.TaskType.FOLLOW_UP: handle_follow_up,
    Task.TaskType.SEND_MESSAGE: handle_send_message,
    Task.TaskType.REPLY_CHECK: handle_reply_check,
}


def _prioritize_claims(queryset):
    """Run human-approved sends before background checks and draft generation."""
    return queryset.annotate(
        _daemon_priority=Case(
            When(task_type=Task.TaskType.SEND_MESSAGE, then=Value(0)),
            When(task_type=Task.TaskType.REPLY_CHECK, then=Value(1)),
            When(task_type=Task.TaskType.FOLLOW_UP, then=Value(2)),
            When(task_type=Task.TaskType.CHECK_PENDING, then=Value(3)),
            When(task_type=Task.TaskType.CONNECT, then=Value(4)),
            default=Value(9),
            output_field=IntegerField(),
        )
    ).order_by("_daemon_priority", "scheduled_at", "id")


def _recent_outreach_cooldown_seconds(session, cfg) -> float:
    """Return remaining cooldown after a real outward LinkedIn action."""
    if not bot_time_limits_enabled():
        return 0.0

    min_interval = float(cfg.get("min_action_interval") or 0)
    if min_interval <= 0:
        return 0.0

    profile = getattr(session, "linkedin_profile", None)
    profile_pk = getattr(profile, "pk", None)
    if not isinstance(profile_pk, int):
        return 0.0

    from linkedin.models import ActionLog

    latest = (
        ActionLog.objects.filter(
            linkedin_profile_id=profile_pk,
            status=ActionLog.Status.SUCCESS,
            action_type__in=[
                ActionLog.ActionType.CONNECT,
                ActionLog.ActionType.FOLLOW_UP,
            ],
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if latest is None:
        return 0.0

    elapsed = (timezone.now() - latest).total_seconds()
    return max(min_interval - elapsed, 0.0)


def _set_task_owner(task: Task, owner_id: int, linkedin_profile_id: int | None = None) -> bool:
    payload = dict(task.payload or {})
    if payload.get("owner_id") == owner_id and (
        linkedin_profile_id is None or payload.get("linkedin_profile_id") == linkedin_profile_id
    ):
        return False
    payload["owner_id"] = owner_id
    if linkedin_profile_id is not None:
        payload["linkedin_profile_id"] = linkedin_profile_id
    task.payload = payload
    task.save(update_fields=["payload"])
    return True


def _backfill_owner_ids_for_scoped_tasks(campaign_ids: list[int]) -> int:
    """Attach owner_id to old per-profile tasks before account-scoped claiming."""
    from chat.models import ChatMessage
    from linkedin.models import ActionLog

    tasks = Task.objects.filter(
        task_type__in=_OWNER_SCOPED_TASK_TYPES,
        status__in=[Task.Status.PENDING, Task.Status.RUNNING],
        payload__campaign_id__in=campaign_ids,
    ).filter(Q(payload__owner_id__isnull=True) | Q(payload__linkedin_profile_id__isnull=True)).order_by("scheduled_at", "id")
    changed = 0

    for task in tasks:
        payload = task.payload or {}
        owner_id = payload.get("owner_id")
        linkedin_profile_id = None

        message_id = payload.get("message_id")
        if message_id:
            message_scope = (
                ChatMessage.objects.filter(pk=message_id)
                .values_list("owner_id", "linkedin_profile_id")
                .first()
            )
            if message_scope:
                owner_id, linkedin_profile_id = message_scope

        public_id = payload.get("public_id")
        campaign_id = payload.get("campaign_id")
        if (owner_id is None or linkedin_profile_id is None) and public_id and campaign_id:
            action_scope = (
                ActionLog.objects.filter(
                    campaign_id=campaign_id,
                    target_public_id=public_id,
                    status=ActionLog.Status.SUCCESS,
                    linkedin_profile__user_id__isnull=False,
                )
                .order_by("-created_at", "-id")
                .values_list("linkedin_profile__user_id", "linkedin_profile_id")
                .first()
            )
            if action_scope:
                owner_id = owner_id or action_scope[0]
                linkedin_profile_id = linkedin_profile_id or action_scope[1]

        if owner_id is not None and _set_task_owner(
            task,
            int(owner_id),
            int(linkedin_profile_id) if linkedin_profile_id is not None else None,
        ):
            changed += 1

    return changed


def _close_old_connections_for_daemon():
    """Refresh stale DB connections without breaking Django TestCase transactions."""
    if any(conn.in_atomic_block for conn in connections.all()):
        return
    close_old_connections()


def _build_qualifiers(campaigns, cfg):
    """Create a qualifier for every campaign, keyed by campaign PK."""
    from crm.models import Lead

    qualifiers: dict[int, BayesianQualifier | KitQualifier] = {}
    n_regular = 0
    for campaign in campaigns:
        if campaign.is_freemium:
            km = campaign.load_ml_model()
            if km:
                qualifiers[campaign.pk] = KitQualifier(km)
                logger.info(colored("Kit model loaded", "cyan") + " for freemium campaign %s", campaign)
            continue
        
        q = BayesianQualifier(
            seed=42,
            n_mc_samples=cfg["qualification_n_mc_samples"],
            campaign=campaign,
        )
        X, y = Lead.get_labeled_arrays(campaign)
        if len(X) > 0:
            q.warm_start(X, y)
            logger.info(
                colored("GP qualifier warm-started", "cyan")
                + " on %d labelled samples (%d positive, %d negative)"
                + " for campaign %s",
                len(y), int((y == 1).sum()), int((y == 0).sum()), campaign,
            )
        qualifiers[campaign.pk] = q
        n_regular += 1

    return qualifiers


# ------------------------------------------------------------------
# Schedule guard
# ------------------------------------------------------------------


def seconds_until_active() -> float:
    """Return seconds to wait before the next active window, or 0 if active now."""
    if not bot_time_limits_enabled() or not ENABLE_ACTIVE_HOURS:
        return 0.0
    tz = ZoneInfo(ACTIVE_TIMEZONE)
    now = timezone.localtime(timezone=tz)

    if now.weekday() not in REST_DAYS and ACTIVE_START_HOUR <= now.hour < ACTIVE_END_HOUR:
        return 0.0

    # Find the next active start: try today first, then subsequent days
    candidate = timezone.make_aware(
        now.replace(hour=ACTIVE_START_HOUR, minute=0, second=0, microsecond=0, tzinfo=None),
        timezone=tz,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() in REST_DAYS:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


# ------------------------------------------------------------------
# Task queue worker
# ------------------------------------------------------------------


def heal_tasks(session):
    """Reconcile task queue with CRM state on daemon startup.

    1. Reset stale 'running' tasks to 'pending' (crashed worker recovery)
    2. Seed one 'connect' task per campaign if none pending
    3. Create 'check_pending' tasks for PENDING profiles without tasks
    4. Create 'follow_up' tasks for CONNECTED profiles without tasks
    """
    from crm.models import Deal
    from linkedin.enums import ProfileState

    cfg = CAMPAIGN_CONFIG
    campaign_ids = [campaign.pk for campaign in session.campaigns]
    session_user_id = getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(session_user_id, int):
        session_user_id = None
    session_profile_id = getattr(getattr(session, "linkedin_profile", None), "pk", None)
    if not isinstance(session_profile_id, int):
        session_profile_id = None

    backfilled = _backfill_owner_ids_for_scoped_tasks(campaign_ids)
    if backfilled:
        logger.info("Backfilled owner_id on %d scoped task(s)", backfilled)

    # 1. Recover stale running tasks
    stale_count = Task.objects.filter(
        status=Task.Status.RUNNING,
        payload__campaign_id__in=campaign_ids,
    ).update(
        status=Task.Status.PENDING,
    )
    if stale_count:
        logger.info("Recovered %d stale running tasks", stale_count)

    # 2. Seed connect tasks per campaign (regular first, freemium deferred)
    for campaign in session.campaigns:
        delay = bot_delay_seconds(CAMPAIGN_CONFIG["connect_delay_seconds"]) if campaign.is_freemium else 0
        enqueue_connect(campaign.pk, delay_seconds=delay)

    # 3. Check_pending tasks for PENDING profiles
    for campaign in session.campaigns:
        session.campaign = campaign
        pending_deals = Deal.objects.filter(
            state=ProfileState.PENDING,
            campaign=campaign,
        ).select_related("lead")

        for deal in pending_deals:
            public_id = deal.lead.public_identifier
            if not public_id:
                continue
            backoff = deal.backoff_hours or cfg["check_pending_recheck_after_hours"]
            enqueue_check_pending(
                campaign.pk,
                public_id,
                backoff_hours=backoff,
                deal=deal,
                owner_id=session_user_id,
                linkedin_profile_id=session_profile_id,
            )

    # 4. Follow_up tasks for CONNECTED profiles
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType

    for campaign in session.campaigns:
        session.campaign = campaign
        connected_deals = Deal.objects.filter(
            state=ProfileState.CONNECTED,
            campaign=campaign,
        ).select_related("lead")

        for deal in connected_deals:
            public_id = deal.lead.public_identifier
            if not public_id:
                continue
            
            # Check for existing pending draft OR pending SEND_MESSAGE task
            has_pending_draft = ChatMessage.objects.filter(
                content_type=ContentType.objects.get_for_model(deal.lead),
                object_id=deal.lead.pk, 
                campaign=campaign,
                owner_id=session_user_id,
                linkedin_profile_id=session_profile_id,
                is_draft=True,
                is_approved=False,
            ).exists()
            
            has_send_task = Task.objects.filter(
                task_type=Task.TaskType.SEND_MESSAGE,
                status__in=[Task.Status.PENDING, Task.Status.RUNNING],
                payload__campaign_id=campaign.pk,
                payload__public_id=public_id,
                payload__owner_id=session_user_id,
            ).filter(
                Q(payload__linkedin_profile_id=session_profile_id) | Q(payload__linkedin_profile_id__isnull=True)
            ).exists()

            if has_pending_draft or has_send_task:
                continue

            enqueue_follow_up(
                campaign.pk,
                public_id,
                delay_seconds=bot_delay_seconds(random.uniform(5, 60)),
                deal=deal,
                owner_id=session_user_id,
                linkedin_profile_id=session_profile_id,
            )


    pending_count = Task.objects.filter(payload__campaign_id__in=campaign_ids).pending().count()
    logger.info("Task queue healed: %d pending tasks", pending_count)

def run_daemon(session):
    cfg = CAMPAIGN_CONFIG
    started_monotonic = time.monotonic()
    max_runtime = bot_delay_seconds(cfg.get("daemon_max_runtime_seconds") or 0)

    qualifiers = _build_qualifiers(session.campaigns, cfg)

    # Startup healing
    heal_tasks(session)

    campaigns = session.campaigns
    if not campaigns:
        logger.error("No campaigns found - cannot start daemon")
        return
    campaign_by_id = {campaign.pk: campaign for campaign in campaigns}
    campaign_ids = list(campaign_by_id)
    session_user_id = getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(session_user_id, int):
        session_user_id = None
    session_profile_id = getattr(getattr(session, "linkedin_profile", None), "pk", None)
    if not isinstance(session_profile_id, int):
        session_profile_id = None

    task_scope = Task.objects.filter(payload__campaign_id__in=campaign_ids).filter(
        ~Q(task_type__in=_OWNER_SCOPED_TASK_TYPES)
        | Q(payload__owner_id=session_user_id)
    ).filter(
        ~Q(task_type__in=_OWNER_SCOPED_TASK_TYPES)
        | Q(payload__linkedin_profile_id=session_profile_id)
        | Q(payload__linkedin_profile_id__isnull=True)
    )

    logger.info(
        colored("Daemon started", "green", attrs=["bold"])
        + " - %d campaigns, task queue worker",
        len(campaigns),
    )

    # Single-threaded: one task at a time. Keep polling forever until the
    # operator stops the process. Only due tasks run; future tasks stay queued
    # while the daemon polls at a short interval instead of sleeping until then.
    while True:
        _close_old_connections_for_daemon()
        if max_runtime > 0 and time.monotonic() - started_monotonic >= max_runtime:
            logger.warning(
                "Daemon runtime cap reached after %.0f minutes - stopping for a long rest",
                max_runtime / 60,
            )
            return

        pause = seconds_until_active()
        if pause > 0:
            h, m = int(pause // 3600), int(pause % 3600 // 60)
            logger.info(
                "Outside active hours for %dh%02dm - polling again in %.0fs",
                h,
                m,
                _IDLE_POLL_INTERVAL_SECONDS,
            )
            time.sleep(_IDLE_POLL_INTERVAL_SECONDS)
            continue

        due_scope = task_scope.filter(status=Task.Status.PENDING, scheduled_at__lte=timezone.now())
        cooldown = _recent_outreach_cooldown_seconds(session, cfg)
        if cooldown > 0:
            due_scope = due_scope.exclude(task_type__in=_OUTREACH_TASK_TYPES)

        claim_scope = _prioritize_claims(due_scope)
        if new_connection_invites_paused():
            claim_scope = claim_scope.exclude(task_type=Task.TaskType.CONNECT)
        task = claim_scope.first()
        if task is None:
            if cooldown > 0 and task_scope.filter(
                task_type__in=_OUTREACH_TASK_TYPES,
                status=Task.Status.PENDING,
                scheduled_at__lte=timezone.now(),
            ).exists():
                logger.info(
                    "Recent outreach action - holding sends/connects for %.0f more minutes",
                    cooldown / 60,
                )
                time.sleep(_IDLE_POLL_INTERVAL_SECONDS)
                continue
            if (
                new_connection_invites_paused()
                and task_scope.filter(task_type=Task.TaskType.CONNECT, status=Task.Status.PENDING).exists()
            ):
                logger.info("New connection invite expansion paused - polling until unpaused")
                time.sleep(_IDLE_POLL_INTERVAL_SECONDS)
                continue
            logger.info(
                "Queue empty - polling again in %.0fs",
                _IDLE_POLL_INTERVAL_SECONDS,
            )
            time.sleep(_IDLE_POLL_INTERVAL_SECONDS)
            continue

        campaign = campaign_by_id.get(task.payload.get("campaign_id"))
        if not campaign:
            task.mark_failed(f"Campaign {task.payload.get('campaign_id')} not found")
            continue

        session.campaign = campaign
        task.mark_running()

        handler = _HANDLERS.get(task.task_type)
        if handler is None:
            task.mark_failed(f"Unknown task type: {task.task_type}")
            continue

        try:
            with failure_diagnostics(session):
                handler(task, session, qualifiers)
            _close_old_connections_for_daemon()
            task.mark_completed()
        except TaskSkipped as e:
            _close_old_connections_for_daemon()
            task.mark_skipped(str(e))
            logger.info("Task %s skipped: %s", task, str(e))
        except Exception:
            error = traceback.format_exc()
            _close_old_connections_for_daemon()
            try:
                task.mark_failed(error)
            except Exception:
                logger.exception(
                    "Task %s failed and could not be marked failed. Original traceback:\n%s",
                    task,
                    error,
                )
            else:
                logger.exception("Task %s failed", task)
            continue

