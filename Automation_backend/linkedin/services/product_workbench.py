from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.utils import timezone

from chat.models import ChatMessage
from crm.models.deal import Deal
from crm.models.lead import Lead
from google_integration.sheet_sync import sync_lead_to_google_sheet
from linkedin.enums import ProfileState
from linkedin.models import ActionLog, Campaign, SiteConfig, Task, OutreachEvent
from linkedin.tasks.connect import enqueue_follow_up


@dataclass
class SafeModeSettings:
    enabled: bool
    global_pause_outreach: bool
    max_bulk_approve: int
    max_bulk_export: int


def _lead_primary_deal(lead: Lead) -> Deal | None:
    return (
        Deal.objects.filter(lead=lead)
        .select_related("campaign")
        .order_by("-update_date")
        .first()
    )


def lead_quality_insights(lead: Lead) -> dict[str, Any]:
    deal = _lead_primary_deal(lead)
    score = 50
    reasons: list[str] = []
    conflicts: list[str] = []

    if lead.first_name and lead.last_name:
        score += 10
        reasons.append("Lead has complete name data.")
    else:
        score -= 8
        reasons.append("Lead name is incomplete.")

    if lead.company_name:
        score += 8
        reasons.append("Company information is present.")
    else:
        score -= 6
        reasons.append("Company information is missing.")

    if lead.profile_data:
        score += 15
        reasons.append("Profile is enriched with LinkedIn data.")
    else:
        score -= 12
        reasons.append("Profile is not enriched yet.")

    if lead.disqualified:
        score = min(score, 5)
        conflicts.append("Lead is globally disqualified.")

    if deal:
        if deal.state == ProfileState.CONNECTED.value:
            score += 20
            reasons.append("Deal is CONNECTED (automation inference — export still requires verified events).")
        elif deal.state == ProfileState.COMPLETED.value:
            score += 15
            reasons.append("Lead is in COMPLETED state.")
        elif deal.state == ProfileState.FAILED.value:
            score -= 20
            reasons.append("Lead is in FAILED state.")
        if deal.reason:
            reasons.append("Qualification reason is available.")
    else:
        reasons.append("No active deal found for lead.")

    duplicate_count = Lead.objects.filter(public_identifier=lead.public_identifier).count()
    if duplicate_count > 1:
        score -= 15
        conflicts.append("Duplicate lead public identifier found.")

    campaign_conflicts = Deal.objects.filter(lead=lead).values("campaign_id").distinct().count()
    if campaign_conflicts > 1:
        score -= 8
        conflicts.append("Lead exists in multiple campaigns.")

    failed_tasks = Task.objects.filter(deal__lead=lead, status=Task.Status.FAILED).count()
    if failed_tasks:
        score -= min(20, failed_tasks * 3)
        conflicts.append(f"{failed_tasks} failed task(s) linked to this lead.")

    score = max(0, min(score, 100))
    next_action = "review"
    if score >= 80:
        next_action = "prioritize"
    elif score <= 35:
        next_action = "recover"

    return {
        "leadId": lead.id,
        "qualityScore": score,
        "reasons": reasons[:8],
        "conflicts": conflicts[:6],
        "nextAction": next_action,
        "dealState": deal.state if deal else "UNQUALIFIED",
    }


def lead_timeline(lead: Lead, limit: int = 50) -> list[dict[str, Any]]:
    lead_ct = ContentType.objects.get_for_model(Lead)
    events: list[dict[str, Any]] = []

    deals = Deal.objects.filter(lead=lead).select_related("campaign").order_by("-update_date")[:limit]
    for d in deals:
        events.append(
            {
                "kind": "deal",
                "at": d.update_date.isoformat(),
                "title": f"Deal moved to {d.state}",
                "detail": d.reason or "",
                "campaign": d.campaign.name if d.campaign_id else "",
            }
        )

    tasks = Task.objects.filter(deal__lead=lead).order_by("-created_at")[:limit]
    for t in tasks:
        events.append(
            {
                "kind": "task",
                "at": t.created_at.isoformat(),
                "title": f"{t.task_type} {t.status}",
                "detail": (t.error or "")[:240],
                "campaign": "",
            }
        )

    actions = ActionLog.objects.filter(target_public_id=lead.public_identifier).select_related("campaign").order_by("-created_at")[:limit]
    for a in actions:
        events.append(
            {
                "kind": "action",
                "at": a.created_at.isoformat(),
                "title": f"{a.action_type} {a.status}",
                "detail": (a.note or "")[:240],
                "campaign": a.campaign.name if a.campaign_id else "",
            }
        )

    oe_qs = OutreachEvent.objects.filter(lead=lead).order_by("-created_at")[:limit]
    for oe in oe_qs:
        events.append(
            {
                "kind": "outreach_event",
                "at": oe.created_at.isoformat(),
                "title": oe.event_type,
                "detail": str(oe.metadata or {})[:240],
                "campaign": "",
            }
        )

    messages = (
        ChatMessage.objects.filter(content_type=lead_ct, object_id=lead.id)
        .select_related("campaign")
        .order_by("-creation_date")[:limit]
    )
    for m in messages:
        events.append(
            {
                "kind": "message",
                "at": m.creation_date.isoformat(),
                "title": "Draft message" if m.is_draft else "Message",
                "detail": (m.content or "")[:240],
                "campaign": m.campaign.name if m.campaign_id else "",
            }
        )

    if lead.sheet_exported_at:
        events.append(
            {
                "kind": "export",
                "at": lead.sheet_exported_at.isoformat(),
                "title": "Exported to Google Sheet",
                "detail": "",
                "campaign": "",
            }
        )

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


def workbench_summary() -> dict[str, Any]:
    now = timezone.now()
    since_day = now - timedelta(days=1)
    connected_qs = Deal.objects.filter(state=ProfileState.CONNECTED.value).select_related("lead", "campaign")

    drafts_pending = ChatMessage.objects.filter(is_draft=True, is_approved=False).count()
    failed_tasks = Task.objects.filter(status=Task.Status.FAILED).count()
    pending_tasks = Task.objects.filter(status=Task.Status.PENDING).count()
    stale_pending = Deal.objects.filter(
        state=ProfileState.PENDING.value,
        update_date__lt=now - timedelta(days=7),
    ).count()

    from linkedin.outreach_tracking import lead_sheet_export_verification

    verified_export_backlog = 0
    connected_awaiting_verification = 0
    for d in connected_qs.filter(lead__sheet_exported_at__isnull=True).select_related("lead").iterator(chunk_size=300):
        if not d.lead:
            continue
        ok, _, _ = lead_sheet_export_verification(d.lead)
        if ok:
            verified_export_backlog += 1
        else:
            connected_awaiting_verification += 1

    sampled = [d for d in connected_qs[:300] if d.lead and d.lead.public_identifier]
    sampled_public_ids = [d.lead.public_identifier for d in sampled]
    active_followups = set(
        Task.objects.filter(
            task_type=Task.TaskType.FOLLOW_UP,
            status__in=[Task.Status.PENDING, Task.Status.RUNNING],
            payload__public_id__in=sampled_public_ids,
        ).values_list("payload__public_id", flat=True)
    )
    no_followup = sum(1 for pid in sampled_public_ids if pid not in active_followups)

    return {
        "stats": {
            "connectedDeals": connected_qs.count(),
            "draftsAwaitingApproval": drafts_pending,
            "failedTasks": failed_tasks,
            "pendingTasks": pending_tasks,
            "stalePendingDeals": stale_pending,
            "connectedWithoutExport": verified_export_backlog,
            "connectedAwaitingVerification": connected_awaiting_verification,
            "connectedWithoutFollowup": no_followup,
            "actions24h": ActionLog.objects.filter(created_at__gte=since_day).count(),
        },
        "inbox": [
            {"key": "draft_approval", "count": drafts_pending, "priority": "high"},
            {"key": "task_failures", "count": failed_tasks, "priority": "high"},
            {"key": "missing_followups", "count": no_followup, "priority": "medium"},
            {"key": "export_backlog", "count": verified_export_backlog, "priority": "medium"},
            {"key": "stale_pending", "count": stale_pending, "priority": "low"},
        ],
    }


def campaign_health() -> list[dict[str, Any]]:
    campaigns = Campaign.objects.all().order_by("name")
    deal_aggregates = {
        row["campaign_id"]: row
        for row in Deal.objects.values("campaign_id").annotate(
            total=Count("id"),
            connected=Count("id", filter=Q(state=ProfileState.CONNECTED.value)),
            completed=Count("id", filter=Q(state=ProfileState.COMPLETED.value)),
            failed=Count("id", filter=Q(state=ProfileState.FAILED.value)),
            pending=Count("id", filter=Q(state=ProfileState.PENDING.value)),
        )
    }
    draft_aggregates = {
        row["campaign_id"]: row["total"]
        for row in ChatMessage.objects.filter(is_draft=True, is_approved=False)
        .values("campaign_id")
        .annotate(total=Count("id"))
    }
    task_failure_aggregates = {
        row["deal__campaign_id"]: row["total"]
        for row in Task.objects.filter(status=Task.Status.FAILED)
        .values("deal__campaign_id")
        .annotate(total=Count("id"))
    }
    followup_aggregates = {
        row["campaign_id"]: row["total"]
        for row in ActionLog.objects.filter(action_type=ActionLog.ActionType.FOLLOW_UP)
        .values("campaign_id")
        .annotate(total=Count("id"))
    }
    items: list[dict[str, Any]] = []
    for c in campaigns:
        ds = deal_aggregates.get(c.id, {})
        total = ds.get("total", 0)
        connected = ds.get("connected", 0)
        completed = ds.get("completed", 0)
        failed = ds.get("failed", 0)
        pending = ds.get("pending", 0)
        drafts = draft_aggregates.get(c.id, 0)
        task_failures = task_failure_aggregates.get(c.id, 0)
        reply_logs = followup_aggregates.get(c.id, 0)
        acceptance = round((connected / max(1, (connected + failed + pending))) * 100, 2)
        conversion = round((completed / max(1, total)) * 100, 2)
        health_score = max(0, min(100, 60 + int(acceptance / 4) + int(conversion / 4) - task_failures))
        items.append(
            {
                "campaignId": c.id,
                "campaignName": c.name,
                "totalDeals": total,
                "connected": connected,
                "completed": completed,
                "failed": failed,
                "pending": pending,
                "draftsAwaitingApproval": drafts,
                "taskFailures": task_failures,
                "followupsLogged": reply_logs,
                "acceptanceRate": acceptance,
                "conversionRate": conversion,
                "healthScore": health_score,
            }
        )
    return items


def recovery_items(limit: int = 200) -> list[dict[str, Any]]:
    rows = (
        Task.objects.filter(status__in=[Task.Status.FAILED, Task.Status.SKIPPED])
        .select_related("deal", "deal__lead")
        .order_by("-ended_at", "-created_at")[:limit]
    )
    items: list[dict[str, Any]] = []
    for t in rows:
        lead = t.deal.lead if t.deal_id and t.deal and t.deal.lead_id else None
        items.append(
            {
                "taskId": t.id,
                "taskType": t.task_type,
                "status": t.status,
                "error": (t.error or "")[:400],
                "dealId": t.deal_id,
                "leadPublicIdentifier": lead.public_identifier if lead else "",
                "campaignId": t.deal.campaign_id if t.deal_id and t.deal else None,
                "scheduledAt": t.scheduled_at.isoformat(),
                "endedAt": t.ended_at.isoformat() if t.ended_at else None,
            }
        )
    return items


def retry_task(task: Task) -> Task:
    payload = dict(task.payload or {})
    existing = Task.objects.filter(
        task_type=task.task_type,
        status=Task.Status.PENDING,
        deal=task.deal,
        payload=payload,
    ).first()
    if existing:
        return existing
    return Task.objects.create(
        task_type=task.task_type,
        status=Task.Status.PENDING,
        scheduled_at=timezone.now(),
        deal=task.deal,
        payload=payload,
    )


def export_preview(limit: int = 250) -> dict[str, Any]:
    from linkedin.outreach_tracking import lead_sheet_export_verification

    connected_deals = Deal.objects.filter(state=ProfileState.CONNECTED.value).select_related("lead", "campaign").order_by("-update_date")[:limit]
    exportable: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for d in connected_deals:
        lead = d.lead
        if not lead:
            continue
        reason = ""
        ok_export, verify_reason, _ = lead_sheet_export_verification(lead)
        if lead.sheet_exported_at:
            reason = "already_exported"
        elif not lead.profile_data:
            reason = "profile_not_enriched"
        elif not lead.linkedin_url:
            reason = "missing_linkedin_url"
        elif not ok_export:
            reason = f"not_verified_for_export:{verify_reason}"

        row = {
            "leadId": lead.id,
            "fullName": f"{lead.first_name} {lead.last_name}".strip() or lead.public_identifier,
            "publicIdentifier": lead.public_identifier,
            "campaign": d.campaign.name if d.campaign_id else "",
            "connectedAt": d.update_date.isoformat(),
            "sheetExportedAt": lead.sheet_exported_at.isoformat() if lead.sheet_exported_at else None,
        }
        if reason:
            row["reason"] = reason
            skipped.append(row)
        else:
            exportable.append(row)
    return {"exportable": exportable, "skipped": skipped}


def export_selected(lead_ids: list[int]) -> dict[str, int]:
    ok = 0
    failed = 0
    for lead in Lead.objects.filter(pk__in=lead_ids):
        if sync_lead_to_google_sheet(lead):
            ok += 1
        else:
            failed += 1
    return {"exported": ok, "failed": failed}


def followup_suggestions(limit: int = 200) -> list[dict[str, Any]]:
    connected = (
        Deal.objects.filter(state=ProfileState.CONNECTED.value)
        .select_related("lead", "campaign")
        .order_by("-update_date")[:limit]
    )
    lead_ct = ContentType.objects.get_for_model(Lead)
    items: list[dict[str, Any]] = []
    lead_ids = [d.lead_id for d in connected if d.lead_id]
    lead_public_ids = [d.lead.public_identifier for d in connected if d.lead and d.lead.public_identifier]
    draft_lead_ids = set(
        ChatMessage.objects.filter(content_type=lead_ct, object_id__in=lead_ids, is_draft=True, is_approved=False).values_list(
            "object_id", flat=True
        )
    )
    send_public_ids = set(
        Task.objects.filter(
            task_type=Task.TaskType.SEND_MESSAGE,
            status__in=[Task.Status.PENDING, Task.Status.RUNNING],
            payload__public_id__in=lead_public_ids,
        ).values_list("payload__public_id", flat=True)
    )
    followup_public_ids = set(
        Task.objects.filter(
            task_type=Task.TaskType.FOLLOW_UP,
            status__in=[Task.Status.PENDING, Task.Status.RUNNING],
            payload__public_id__in=lead_public_ids,
        ).values_list("payload__public_id", flat=True)
    )

    for d in connected:
        lead = d.lead
        if not lead or not lead.public_identifier:
            continue
        has_draft = lead.id in draft_lead_ids
        has_send = lead.public_identifier in send_public_ids
        has_followup = lead.public_identifier in followup_public_ids

        action = "queue_followup"
        rationale = "No active follow-up task found."
        if has_send:
            action = "wait_send_message"
            rationale = "A send_message task is already queued."
        elif has_draft:
            action = "approve_draft"
            rationale = "Unapproved draft is ready for review."
        elif has_followup:
            action = "wait_followup"
            rationale = "Follow-up task already queued."

        items.append(
            {
                "leadId": lead.id,
                "dealId": d.id,
                "campaignId": d.campaign_id,
                "campaign": d.campaign.name if d.campaign_id else "",
                "fullName": f"{lead.first_name} {lead.last_name}".strip() or lead.public_identifier,
                "publicIdentifier": lead.public_identifier,
                "action": action,
                "rationale": rationale,
            }
        )
    return items


def queue_followups_for_leads(lead_ids: list[int]) -> dict[str, int]:
    enqueued = 0
    skipped = 0
    deals = Deal.objects.filter(lead_id__in=lead_ids, state=ProfileState.CONNECTED.value).select_related("lead", "campaign")
    for d in deals:
        if not d.lead or not d.lead.public_identifier:
            skipped += 1
            continue
        enqueue_follow_up(d.campaign_id, d.lead.public_identifier, delay_seconds=10, deal=d)
        enqueued += 1
    return {"enqueued": enqueued, "skipped": skipped}


def get_safe_mode_settings() -> SafeModeSettings:
    cfg = SiteConfig.load()
    return SafeModeSettings(
        enabled=bool(getattr(cfg, "safe_mode_enabled", True)),
        global_pause_outreach=bool(getattr(cfg, "global_pause_outreach", False)),
        max_bulk_approve=int(getattr(cfg, "max_bulk_approve", 25)),
        max_bulk_export=int(getattr(cfg, "max_bulk_export", 50)),
    )


def set_safe_mode_settings(payload: dict[str, Any]) -> SafeModeSettings:
    cfg = SiteConfig.load()
    try:
        max_bulk_approve = int(payload.get("maxBulkApprove", cfg.max_bulk_approve))
        max_bulk_export = int(payload.get("maxBulkExport", cfg.max_bulk_export))
    except (TypeError, ValueError):
        max_bulk_approve = cfg.max_bulk_approve
        max_bulk_export = cfg.max_bulk_export
    cfg.safe_mode_enabled = bool(payload.get("enabled", cfg.safe_mode_enabled))
    cfg.global_pause_outreach = bool(payload.get("globalPauseOutreach", cfg.global_pause_outreach))
    cfg.max_bulk_approve = max(1, min(max_bulk_approve, 500))
    cfg.max_bulk_export = max(1, min(max_bulk_export, 1000))
    cfg.save(update_fields=["safe_mode_enabled", "global_pause_outreach", "max_bulk_approve", "max_bulk_export"])
    return get_safe_mode_settings()
