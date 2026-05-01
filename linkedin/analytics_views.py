"""Staff analytics dashboard: CRM, tasks, action logs, and time-series charts."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from chat.models import ChatMessage
from crm.models.deal import Deal
from crm.models.lead import Lead
from linkedin.models import ActionLog, Campaign, LinkedInProfile, SearchKeyword, Task


def _date_range_days(n: int) -> tuple[timezone.datetime, list[str]]:
    now = timezone.now()
    end_d = now.date()
    start_d = end_d - timedelta(days=n - 1)
    labels = [(start_d + timedelta(days=i)).isoformat() for i in range(n)]
    start_dt = timezone.make_aware(
        datetime.combine(start_d, datetime.min.time()),
        timezone=timezone.get_current_timezone(),
    )
    return start_dt, labels


def _series_from_day_counts(
    labels: list[str],
    rows: list[tuple[object, str, int]],
) -> dict[str, list[int]]:
    keys = sorted({k for _, k, _ in rows})
    if not keys:
        return {}
    by_day: dict[str, dict[str, int]] = {lab: {k: 0 for k in keys} for lab in labels}
    for day, key, c in rows:
        d = day.date() if hasattr(day, "date") else day
        lab = d.isoformat() if hasattr(d, "isoformat") else str(day)
        if lab in by_day and key in by_day[lab]:
            by_day[lab][key] += c
    return {k: [by_day[lab][k] for lab in labels] for k in keys}


@staff_member_required
def analytics_dashboard(request: HttpRequest) -> HttpResponse:
    start_30d, labels_30d = _date_range_days(30)
    now = timezone.now()
    n_days = len(labels_30d)
    zero_series = [0] * n_days

    # --- Fewer DB round-trips: conditional aggregates per model ---
    lead_a = Lead.objects.aggregate(
        leads=Count("pk"),
        leads_disqualified=Count("pk", filter=Q(disqualified=True)),
    )
    deal_a = Deal.objects.aggregate(
        deals=Count("pk"),
        pipeline_leads=Count("lead", distinct=True),
    )
    prof_a = LinkedInProfile.objects.aggregate(
        linkedin_profiles=Count("pk"),
        linkedin_profiles_active=Count("pk", filter=Q(active=True)),
    )
    kw_a = SearchKeyword.objects.aggregate(
        search_keywords=Count("pk"),
        search_keywords_used=Count("pk", filter=Q(used=True)),
    )
    task_a = Task.objects.aggregate(
        tasks=Count("pk"),
        tasks_pending=Count("pk", filter=Q(status=Task.Status.PENDING)),
    )
    msg_a = ChatMessage.objects.aggregate(
        messages=Count("pk"),
        messages_drafts=Count("pk", filter=Q(is_draft=True)),
    )

    totals = {
        "leads": lead_a["leads"] or 0,
        "leads_disqualified": lead_a["leads_disqualified"] or 0,
        "deals": deal_a["deals"] or 0,
        "pipeline_leads": deal_a["pipeline_leads"] or 0,
        "campaigns": Campaign.objects.count(),
        "linkedin_profiles": prof_a["linkedin_profiles"] or 0,
        "linkedin_profiles_active": prof_a["linkedin_profiles_active"] or 0,
        "search_keywords": kw_a["search_keywords"] or 0,
        "search_keywords_used": kw_a["search_keywords_used"] or 0,
        "action_logs": ActionLog.objects.count(),
        "tasks": task_a["tasks"] or 0,
        "tasks_pending": task_a["tasks_pending"] or 0,
        "messages": msg_a["messages"] or 0,
        "messages_drafts": msg_a["messages_drafts"] or 0,
    }

    action_all = list(
        ActionLog.objects.values("action_type", "status").annotate(c=Count("id"))
    )

    deal_by_state = dict(
        Deal.objects.values("state").annotate(c=Count("id")).values_list("state", "c")
    )

    task_by_status = dict(
        Task.objects.values("status").annotate(c=Count("id")).values_list("status", "c")
    )
    task_by_type = dict(
        Task.objects.values("task_type").annotate(c=Count("id")).values_list("task_type", "c")
    )

    action_day_rows = [
        (row["day"], row["action_type"], row["c"])
        for row in (
            ActionLog.objects.filter(created_at__gte=start_30d)
            .annotate(day=TruncDate("created_at"))
            .values("day", "action_type")
            .annotate(c=Count("id"))
        )
    ]

    invites_30d = sum(c for _, t, c in action_day_rows if t == ActionLog.ActionType.CONNECT)
    followups_30d = sum(c for _, t, c in action_day_rows if t == ActionLog.ActionType.FOLLOW_UP)

    action_series = _series_from_day_counts(labels_30d, action_day_rows)
    connect_series = action_series.get("connect", list(zero_series))
    follow_series = action_series.get("follow_up", list(zero_series))

    task_day_rows = [
        (row["day"], row["status"], row["c"])
        for row in (
            Task.objects.filter(
                ended_at__isnull=False,
                ended_at__gte=start_30d,
                status__in=[Task.Status.COMPLETED, Task.Status.FAILED, Task.Status.SKIPPED],
            )
            .annotate(day=TruncDate("ended_at"))
            .values("day", "status")
            .annotate(c=Count("id"))
        )
    ]
    task_series = _series_from_day_counts(labels_30d, task_day_rows)

    lead_day_rows = [
        (r["day"], "leads", r["c"])
        for r in (
            Lead.objects.filter(creation_date__gte=start_30d)
            .annotate(day=TruncDate("creation_date"))
            .values("day")
            .annotate(c=Count("id"))
        )
    ]
    lead_series = _series_from_day_counts(labels_30d, lead_day_rows).get("leads", list(zero_series))

    top_campaigns = list(
        Campaign.objects.annotate(deal_count=Count("deals"))
        .order_by("-deal_count")[:8]
        .values("id", "name", "deal_count")
    )

    chart_payload = {
        "labels30": labels_30d,
        "actionsConnect": connect_series,
        "actionsFollowUp": follow_series,
        "tasksCompleted": task_series.get(Task.Status.COMPLETED, list(zero_series)),
        "tasksFailed": task_series.get(Task.Status.FAILED, list(zero_series)),
        "tasksSkipped": task_series.get(Task.Status.SKIPPED, list(zero_series)),
        "leadsCreated": lead_series,
        "dealStates": {"labels": list(deal_by_state.keys()), "values": list(deal_by_state.values())},
        "taskStatus": {"labels": list(task_by_status.keys()), "values": list(task_by_status.values())},
        "taskTypes": {"labels": list(task_by_type.keys()), "values": list(task_by_type.values())},
    }

    context = {
        "totals": totals,
        "deal_by_state": deal_by_state,
        "task_by_status": task_by_status,
        "task_by_type": task_by_type,
        "action_all": action_all,
        "top_campaigns": top_campaigns,
        "invites_30d": invites_30d,
        "followups_30d": followups_30d,
        "chart_data": chart_payload,
        "generated_at": now,
    }
    return render(request, "linkedin/analytics.html", context)
