from __future__ import annotations

from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from chat.models import ChatMessage
from crm.models.deal import Deal
from crm.models.lead import Lead
from linkedin.enums import ProfileState
from linkedin.models import ActionLog, Campaign, LinkedInProfile, Task

def dashboard_callback(request, context):
    """
    Enhanced EshLead Dashboard Callback.
    Returns structured data for the Unfold Dashboard.
    """
    from django.db.models import Count, Q
    from django.urls import reverse
    from chat.models import ChatMessage
    from crm.models.deal import Deal

    from django.utils import timezone
    from linkedin.enums import ProfileState
    today = timezone.localdate()
    last_week = timezone.now() - timedelta(days=7)

    drafts_awaiting = ChatMessage.objects.filter(is_draft=True, is_approved=False).count()
    try:
        drafts_url = (
            reverse("admin:chat_chatmessage_changelist")
            + "?is_draft__exact=1&is_approved__exact=0"
        )
    except Exception:
        drafts_url = "/admin/chat/chatmessage/?is_draft__exact=1&is_approved__exact=0"
    
    # [LOW-04] Three separate queries: Lead count, Deal aggregates, ActionLog aggregates.
    # These are distinct tables with no join relationship; batching isn't possible.
    total_leads = Lead.objects.count()
    
    # Batch Deal stats in 1 query
    deal_stats = Deal.objects.aggregate(
        total=Count("id"),
        connected=Count("id", filter=Q(state=ProfileState.CONNECTED)),
        failed=Count("id", filter=Q(state=ProfileState.FAILED)),
        pending=Count("id", filter=Q(state=ProfileState.PENDING)),
        completed=Count("id", filter=Q(state=ProfileState.COMPLETED)),
    )
    
    # Batch ActionLog stats in 1 query
    action_stats = ActionLog.objects.aggregate(
        today=Count("id", filter=Q(created_at__date=today)),
        week=Count("id", filter=Q(created_at__gte=last_week)),
    )
    
    total_pipeline = deal_stats["total"]
    connected = deal_stats["connected"]
    failed = deal_stats["failed"]
    pending = deal_stats["pending"]
    completed = deal_stats["completed"]
    actions_today = action_stats["today"]

    acceptance_rate = (connected / (connected + pending + failed) * 100) if (connected + pending + failed) > 0 else 0
    conversion_rate = (completed / total_pipeline * 100) if total_pipeline > 0 else 0

    active_profile = LinkedInProfile.objects.filter(active=True).first()

    google_status = "Disconnected"
    google_email = ""
    try:
        from google_integration.models import GoogleAccount
        ga = GoogleAccount.objects.filter(user=request.user).first()
        if ga and ga.is_connected:
            google_status = "Connected"
            google_email = ga.google_email
    except Exception:
        pass

    context.update({
        "greeting": "EshLead Console",
        "tagline": "Autonomous B2B Lead Generation Active",
        "google_status": google_status,
        "google_email": google_email,
        "google_url": "/admin/google/",
        "kpi": [
            {
                "title": "Total Leads",
                "metric": str(total_leads),
                "icon": "users",
                "color": "info",
            },
            {
                "title": "Acceptance Rate",
                "metric": f"{acceptance_rate:.1f}%",
                "icon": "user_check",
                "color": "success" if acceptance_rate > 30 else "warning",
            },
            {
                "title": "Drafts awaiting approval",
                "metric": str(drafts_awaiting),
                "icon": "mark_email_unread",
                "color": "warning" if drafts_awaiting else "success",
                "url": drafts_url,
            },
            {
                "title": "Actions Today",
                "metric": str(actions_today),
                "icon": "activity",
                "color": "indigo",
            },
            {
                "title": "Conversion",
                "metric": f"{conversion_rate:.1f}%",
                "icon": "trending_up",
                "color": "primary",
            },
        ],
        "drafts_awaiting": drafts_awaiting,
        "drafts_url": drafts_url,
        "profile_status": "🟢 CONNECTED" if (active_profile and active_profile.cookie_data) else "🔴 DISCONNECTED",
    })

    return context


def _user_payload(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "isStaff": user.is_staff,
        "isSuperuser": user.is_superuser,
    }


@ensure_csrf_cookie
@require_GET
def api_csrf(request):
    return JsonResponse({"ok": True, "csrfToken": get_token(request)})


@csrf_exempt
@require_http_methods(["POST"])
def api_login(request):
    import json

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload"}, status=400)

    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        return JsonResponse({"ok": False, "error": "username and password are required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if not user:
        return JsonResponse({"ok": False, "error": "Invalid credentials"}, status=401)
    if not user.is_staff:
        return JsonResponse({"ok": False, "error": "Staff access required"}, status=403)

    login(request, user)
    return JsonResponse({"ok": True, "user": _user_payload(user)})


@csrf_exempt
@require_http_methods(["POST"])
def api_logout(request):
    logout(request)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_me(request):
    return JsonResponse({"ok": True, "user": _user_payload(request.user)})


@login_required
@require_GET
def api_dashboard(request):
    from django.db.models import Count, Q
    from django.utils import timezone

    today = timezone.localdate()
    last_week = timezone.now() - timedelta(days=7)

    total_leads = Lead.objects.count()
    deal_stats = Deal.objects.aggregate(
        total=Count("id"),
        connected=Count("id", filter=Q(state=ProfileState.CONNECTED.value)),
        failed=Count("id", filter=Q(state=ProfileState.FAILED.value)),
        pending=Count("id", filter=Q(state=ProfileState.PENDING.value)),
        completed=Count("id", filter=Q(state=ProfileState.COMPLETED.value)),
    )
    action_stats = ActionLog.objects.aggregate(
        today=Count("id", filter=Q(created_at__date=today)),
        week=Count("id", filter=Q(created_at__gte=last_week)),
    )
    drafts_awaiting = ChatMessage.objects.filter(is_draft=True, is_approved=False).count()

    connected = deal_stats["connected"] or 0
    failed = deal_stats["failed"] or 0
    pending = deal_stats["pending"] or 0
    total_pipeline = deal_stats["total"] or 0
    completed = deal_stats["completed"] or 0

    acceptance_rate = (connected / (connected + pending + failed) * 100) if (connected + pending + failed) > 0 else 0.0
    conversion_rate = (completed / total_pipeline * 100) if total_pipeline > 0 else 0.0

    google_status = {"connected": False, "email": ""}
    try:
        from google_integration.models import GoogleAccount

        ga = GoogleAccount.objects.filter(user=request.user).first()
        if ga and ga.is_connected:
            google_status = {"connected": True, "email": ga.google_email or ""}
    except Exception:
        pass

    return JsonResponse(
        {
            "ok": True,
            "stats": {
                "totalLeads": total_leads,
                "pipelineTotal": total_pipeline,
                "connected": connected,
                "pending": pending,
                "failed": failed,
                "completed": completed,
                "actionsToday": action_stats["today"] or 0,
                "actionsWeek": action_stats["week"] or 0,
                "acceptanceRate": round(acceptance_rate, 2),
                "conversionRate": round(conversion_rate, 2),
                "draftsAwaitingApproval": drafts_awaiting,
            },
            "google": google_status,
        }
    )


def _parse_int(value: str | None, default: int, minimum: int, maximum: int):
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


@login_required
@require_GET
def api_campaigns(request):
    qs = Campaign.objects.all().order_by("name")
    data = [
        {
            "id": c.id,
            "name": c.name,
            "isFreemium": c.is_freemium,
            "actionFraction": c.action_fraction,
            "bookingLink": c.booking_link,
            "objective": c.campaign_objective,
            "users": [u.username for u in c.users.all()],
        }
        for c in qs
    ]
    return JsonResponse({"ok": True, "items": data})


@login_required
@require_GET
def api_leads(request):
    from django.db.models import OuterRef, Q, Subquery

    page = _parse_int(request.GET.get("page"), 1, 1, 100000)
    page_size = _parse_int(request.GET.get("pageSize"), 25, 1, 200)
    search = (request.GET.get("q") or "").strip()
    state = (request.GET.get("state") or "").strip()

    latest_state = Deal.objects.filter(lead_id=OuterRef("pk")).order_by("-update_date").values("state")[:1]
    qs = Lead.objects.all().annotate(current_state=Subquery(latest_state)).order_by("-update_date")
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(company_name__icontains=search)
            | Q(public_identifier__icontains=search)
        )
    if state:
        qs = qs.filter(current_state=state)

    total = qs.count()
    start = (page - 1) * page_size
    rows = qs[start : start + page_size]

    items = [
        {
            "id": l.id,
            "fullName": f"{l.first_name} {l.last_name}".strip() or l.public_identifier,
            "firstName": l.first_name,
            "lastName": l.last_name,
            "companyName": l.company_name,
            "linkedinUrl": l.linkedin_url,
            "publicIdentifier": l.public_identifier,
            "state": getattr(l, "current_state", None) or "UNQUALIFIED",
            "sheetExportedAt": l.sheet_exported_at.isoformat() if l.sheet_exported_at else None,
            "updatedAt": l.update_date.isoformat(),
        }
        for l in rows
    ]

    return JsonResponse({"ok": True, "items": items, "pagination": {"page": page, "pageSize": page_size, "total": total}})


@login_required
@require_GET
def api_deals(request):
    page = _parse_int(request.GET.get("page"), 1, 1, 100000)
    page_size = _parse_int(request.GET.get("pageSize"), 25, 1, 200)
    state = (request.GET.get("state") or "").strip()
    campaign_id = request.GET.get("campaignId")

    qs = Deal.objects.select_related("lead", "campaign").order_by("-update_date")
    if state:
        qs = qs.filter(state=state)
    if campaign_id:
        qs = qs.filter(campaign_id=campaign_id)

    total = qs.count()
    start = (page - 1) * page_size
    rows = qs[start : start + page_size]
    items = [
        {
            "id": d.id,
            "state": d.state,
            "closingReason": d.closing_reason,
            "reason": d.reason,
            "connectAttempts": d.connect_attempts,
            "backoffHours": d.backoff_hours,
            "campaign": {"id": d.campaign_id, "name": d.campaign.name},
            "lead": {
                "id": d.lead_id,
                "name": f"{d.lead.first_name} {d.lead.last_name}".strip() or d.lead.public_identifier,
                "publicIdentifier": d.lead.public_identifier,
                "linkedinUrl": d.lead.linkedin_url,
            },
            "createdAt": d.creation_date.isoformat(),
            "updatedAt": d.update_date.isoformat(),
        }
        for d in rows
    ]
    return JsonResponse({"ok": True, "items": items, "pagination": {"page": page, "pageSize": page_size, "total": total}})


@login_required
@require_GET
def api_tasks(request):
    page = _parse_int(request.GET.get("page"), 1, 1, 100000)
    page_size = _parse_int(request.GET.get("pageSize"), 25, 1, 200)
    status = (request.GET.get("status") or "").strip()

    qs = Task.objects.select_related("deal", "deal__lead").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)

    total = qs.count()
    start = (page - 1) * page_size
    rows = qs[start : start + page_size]
    items = [
        {
            "id": t.id,
            "taskType": t.task_type,
            "status": t.status,
            "scheduledAt": t.scheduled_at.isoformat(),
            "startedAt": t.started_at.isoformat() if t.started_at else None,
            "endedAt": t.ended_at.isoformat() if t.ended_at else None,
            "error": t.error,
            "payload": t.payload,
            "dealId": t.deal_id,
        }
        for t in rows
    ]
    return JsonResponse({"ok": True, "items": items, "pagination": {"page": page, "pageSize": page_size, "total": total}})


@login_required
@require_GET
def api_message_drafts(request):
    qs = (
        ChatMessage.objects.filter(is_draft=True, is_approved=False)
        .select_related("campaign", "owner")
        .order_by("-creation_date")
    )
    items = []
    for m in qs:
        lead_name = ""
        lead_public_id = ""
        obj = m.content_object
        if obj and obj.__class__.__name__ == "Lead":
            lead_name = f"{obj.first_name} {obj.last_name}".strip() or obj.public_identifier
            lead_public_id = obj.public_identifier

        items.append(
            {
                "id": m.id,
                "content": m.content,
                "createdAt": m.creation_date.isoformat(),
                "campaign": m.campaign.name if m.campaign else "",
                "campaignId": m.campaign_id,
                "owner": m.owner.username if m.owner else "",
                "leadName": lead_name,
                "leadPublicIdentifier": lead_public_id,
            }
        )
    return JsonResponse({"ok": True, "items": items})


@login_required
@require_GET
def api_action_logs(request):
    page = _parse_int(request.GET.get("page"), 1, 1, 100000)
    page_size = _parse_int(request.GET.get("pageSize"), 25, 1, 200)
    action_type = (request.GET.get("type") or "").strip()
    status = (request.GET.get("status") or "").strip()
    profile_id = request.GET.get("profileId")
    campaign_id = request.GET.get("campaignId")

    qs = ActionLog.objects.select_related("linkedin_profile", "linkedin_profile__user", "campaign").order_by("-created_at")
    if action_type:
        qs = qs.filter(action_type=action_type)
    if status:
        qs = qs.filter(status=status)
    if profile_id:
        qs = qs.filter(linkedin_profile_id=profile_id)
    if campaign_id:
        qs = qs.filter(campaign_id=campaign_id)

    total = qs.count()
    start = (page - 1) * page_size
    rows = qs[start : start + page_size]
    items = [
        {
            "id": a.id,
            "actionType": a.action_type,
            "status": a.status,
            "targetName": a.target_name,
            "targetPublicId": a.target_public_id,
            "note": a.note,
            "createdAt": a.created_at.isoformat(),
            "campaign": {"id": a.campaign_id, "name": a.campaign.name if a.campaign else ""},
            "profile": {
                "id": a.linkedin_profile_id,
                "username": a.linkedin_profile.linkedin_username if a.linkedin_profile else "",
                "djangoUser": a.linkedin_profile.user.username if a.linkedin_profile and a.linkedin_profile.user else "",
            },
        }
        for a in rows
    ]
    return JsonResponse({"ok": True, "items": items, "pagination": {"page": page, "pageSize": page_size, "total": total}})


@login_required
@require_GET
def api_linkedin_profiles(request):
    qs = LinkedInProfile.objects.select_related("user").order_by("user__username")
    items = [
        {
            "id": p.id,
            "djangoUser": p.user.username,
            "djangoEmail": p.user.email,
            "linkedinUsername": p.linkedin_username,
            "active": p.active,
            "subscribeNewsletter": p.subscribe_newsletter,
            "newsletterProcessed": p.newsletter_processed,
            "legalAccepted": p.legal_accepted,
            "connectDailyLimit": p.connect_daily_limit,
            "connectWeeklyLimit": p.connect_weekly_limit,
            "followUpDailyLimit": p.follow_up_daily_limit,
            "hasCookies": bool(p.cookie_data),
        }
        for p in qs
    ]
    return JsonResponse({"ok": True, "items": items})


@login_required
@require_http_methods(["POST"])
def api_linkedin_profile_toggle(request, profile_id: int):
    try:
        profile = LinkedInProfile.objects.get(pk=profile_id)
    except LinkedInProfile.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Profile not found"}, status=404)

    profile.active = not profile.active
    profile.save(update_fields=["active"])
    return JsonResponse({"ok": True, "active": profile.active})


@login_required
@require_GET
def api_search_keywords(request):
    from linkedin.models import SearchKeyword

    page = _parse_int(request.GET.get("page"), 1, 1, 100000)
    page_size = _parse_int(request.GET.get("pageSize"), 50, 1, 500)
    campaign_id = request.GET.get("campaignId")
    used = request.GET.get("used")

    qs = SearchKeyword.objects.select_related("campaign").order_by("-id")
    if campaign_id:
        qs = qs.filter(campaign_id=campaign_id)
    if used in {"true", "false"}:
        qs = qs.filter(used=(used == "true"))

    total = qs.count()
    start = (page - 1) * page_size
    rows = qs[start : start + page_size]
    items = [
        {
            "id": k.id,
            "keyword": k.keyword,
            "used": k.used,
            "usedAt": k.used_at.isoformat() if k.used_at else None,
            "campaign": {"id": k.campaign_id, "name": k.campaign.name if k.campaign else ""},
        }
        for k in rows
    ]
    return JsonResponse({"ok": True, "items": items, "pagination": {"page": page, "pageSize": page_size, "total": total}})


@login_required
@require_http_methods(["POST"])
def api_search_keywords_create(request):
    import json as _json
    from linkedin.models import SearchKeyword

    try:
        payload = _json.loads(request.body or b"{}")
    except _json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload"}, status=400)

    campaign_id = payload.get("campaignId")
    keyword = (payload.get("keyword") or "").strip()
    if not campaign_id or not keyword:
        return JsonResponse({"ok": False, "error": "campaignId and keyword are required"}, status=400)

    try:
        campaign = Campaign.objects.get(pk=campaign_id)
    except Campaign.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Campaign not found"}, status=404)

    obj, created = SearchKeyword.objects.get_or_create(campaign=campaign, keyword=keyword)
    return JsonResponse(
        {
            "ok": True,
            "created": created,
            "item": {
                "id": obj.id,
                "keyword": obj.keyword,
                "used": obj.used,
                "usedAt": obj.used_at.isoformat() if obj.used_at else None,
                "campaign": {"id": obj.campaign_id, "name": obj.campaign.name},
            },
        }
    )


@login_required
@require_http_methods(["DELETE"])
def api_search_keywords_delete(request, keyword_id: int):
    from linkedin.models import SearchKeyword

    try:
        SearchKeyword.objects.filter(pk=keyword_id).delete()
    except Exception as exc:  # pragma: no cover
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_site_config(request):
    from linkedin.models import SiteConfig

    cfg = SiteConfig.load()
    return JsonResponse(
        {
            "ok": True,
            "config": {
                "llmProvider": cfg.llm_provider,
                "aiModel": cfg.ai_model,
                "llmApiBase": cfg.llm_api_base,
                "azureDeployment": cfg.azure_deployment,
                "azureApiVersion": cfg.azure_api_version,
                "hasLlmApiKey": bool(cfg.llm_api_key),
                "googleSheetSyncEnabled": cfg.google_sheet_sync_enabled,
                "googleSheetId": cfg.google_sheet_id,
                "googleSheetTab": cfg.google_sheet_tab,
                "googleSheetSyncUserId": cfg.google_sheet_sync_user_id,
            },
            "providerChoices": [
                {"value": v, "label": label}
                for v, label in cfg.LLM_PROVIDER_CHOICES
            ],
        }
    )


@login_required
@require_http_methods(["POST"])
def api_site_config_save(request):
    import json as _json
    from linkedin.models import SiteConfig

    try:
        payload = _json.loads(request.body or b"{}")
    except _json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload"}, status=400)

    cfg = SiteConfig.load()
    provider = payload.get("llmProvider")
    if provider is not None:
        provider = str(provider).strip().lower()
        allowed = {value for value, _label in cfg.LLM_PROVIDER_CHOICES}
        if provider not in allowed:
            return JsonResponse({"ok": False, "error": f"Unsupported llmProvider: {provider}"}, status=400)
        payload["llmProvider"] = provider

    fields = {
        "llm_provider": payload.get("llmProvider"),
        "ai_model": payload.get("aiModel"),
        "llm_api_base": payload.get("llmApiBase"),
        "azure_deployment": payload.get("azureDeployment"),
        "azure_api_version": payload.get("azureApiVersion"),
        "google_sheet_sync_enabled": payload.get("googleSheetSyncEnabled"),
        "google_sheet_id": payload.get("googleSheetId"),
        "google_sheet_tab": payload.get("googleSheetTab"),
    }
    for attr, value in fields.items():
        if value is not None:
            setattr(cfg, attr, value.strip() if isinstance(value, str) else value)

    new_key = payload.get("llmApiKey")
    if new_key is not None and new_key != "":
        cfg.llm_api_key = new_key

    cfg.save()
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_analytics(request):
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    days = _parse_int(request.GET.get("days"), 14, 1, 90)
    since = timezone.now() - timedelta(days=days)

    actions = (
        ActionLog.objects.filter(created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day", "action_type")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    daily_buckets: dict[str, dict[str, int]] = {}
    for row in actions:
        d = row["day"].isoformat()
        bucket = daily_buckets.setdefault(d, {"connect": 0, "follow_up": 0})
        bucket[row["action_type"]] = row["count"]

    daily = [
        {"date": d, "connect": v.get("connect", 0), "followUp": v.get("follow_up", 0)}
        for d, v in sorted(daily_buckets.items())
    ]

    deal_states = (
        Deal.objects.values("state").annotate(count=Count("id")).order_by("-count")
    )
    states = [{"state": row["state"], "count": row["count"]} for row in deal_states]

    task_states = (
        Task.objects.values("status").annotate(count=Count("id")).order_by("-count")
    )
    tasks_summary = [{"status": row["status"], "count": row["count"]} for row in task_states]

    top_campaigns = (
        Deal.objects.values("campaign_id", "campaign__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )
    campaigns = [
        {"id": row["campaign_id"], "name": row["campaign__name"], "count": row["count"]}
        for row in top_campaigns
    ]

    return JsonResponse(
        {
            "ok": True,
            "rangeDays": days,
            "daily": daily,
            "dealStates": states,
            "taskStates": tasks_summary,
            "topCampaigns": campaigns,
        }
    )


@login_required
@require_GET
def api_messaging_diagnostics(request):
    """Snapshot of HITL messaging health: connected deals vs drafts vs queued tasks."""
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType
    from crm.models import Deal
    from crm.models.lead import Lead
    from linkedin.enums import ProfileState
    from linkedin.models import SiteConfig
    from linkedin.llm import validate_llm_site_config

    cfg = SiteConfig.load()

    connected_qs = Deal.objects.filter(state=ProfileState.CONNECTED).select_related("lead")
    connected_count = connected_qs.count()

    lead_ct = ContentType.objects.get_for_model(Lead)
    drafts_total = ChatMessage.objects.filter(content_type=lead_ct, is_draft=True).count()
    drafts_unapproved = ChatMessage.objects.filter(
        content_type=lead_ct, is_draft=True, is_approved=False,
    ).count()

    pending_followups = Task.objects.filter(
        task_type=Task.TaskType.FOLLOW_UP, status=Task.Status.PENDING,
    ).count()
    failed_followups = Task.objects.filter(
        task_type=Task.TaskType.FOLLOW_UP, status=Task.Status.FAILED,
    ).count()
    pending_sends = Task.objects.filter(
        task_type=Task.TaskType.SEND_MESSAGE, status=Task.Status.PENDING,
    ).count()

    last_failed = (
        Task.objects.filter(task_type=Task.TaskType.FOLLOW_UP, status=Task.Status.FAILED)
        .order_by("-ended_at", "-created_at")
        .values("id", "error", "ended_at")
        .first()
    )

    leads_without_draft = []
    for deal in connected_qs[:200]:
        lead = deal.lead
        if not lead or not lead.public_identifier:
            continue
        has_draft = ChatMessage.objects.filter(
            content_type=lead_ct, object_id=lead.pk, is_draft=True,
        ).exists()
        has_followup = Task.objects.filter(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            payload__public_id=lead.public_identifier,
        ).exists()
        if not has_draft and not has_followup:
            leads_without_draft.append({
                "leadId": lead.id,
                "publicIdentifier": lead.public_identifier,
                "fullName": f"{lead.first_name} {lead.last_name}".strip() or lead.public_identifier,
                "campaign": deal.campaign.name if deal.campaign_id else "",
            })

    llm_ok, _ = validate_llm_site_config(cfg)

    return JsonResponse({
        "ok": True,
        "diagnostics": {
            "connectedDeals": connected_count,
            "draftsTotal": drafts_total,
            "draftsUnapproved": drafts_unapproved,
            "pendingFollowupTasks": pending_followups,
            "failedFollowupTasks": failed_followups,
            "pendingSendMessageTasks": pending_sends,
            "llmConfigured": llm_ok,
            "lastFailedFollowup": (
                {
                    "taskId": last_failed["id"],
                    "endedAt": last_failed["ended_at"].isoformat() if last_failed and last_failed.get("ended_at") else None,
                    "error": (last_failed.get("error") or "")[:500],
                }
                if last_failed
                else None
            ),
            "leadsWithoutDraft": leads_without_draft,
        },
    })


@login_required
@require_http_methods(["POST"])
def api_messaging_heal(request):
    """Backfill FOLLOW_UP tasks for CONNECTED deals lacking drafts/queued tasks."""
    import random as _random
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType
    from crm.models import Deal
    from linkedin.enums import ProfileState
    from linkedin.tasks.connect import enqueue_follow_up

    deals = Deal.objects.filter(state=ProfileState.CONNECTED).select_related("lead", "campaign")
    enqueued = 0
    skipped = 0

    for deal in deals:
        lead = deal.lead
        if not lead or not lead.public_identifier:
            skipped += 1
            continue

        lead_ct = ContentType.objects.get_for_model(lead.__class__)
        has_draft = ChatMessage.objects.filter(
            content_type=lead_ct, object_id=lead.pk, is_draft=True,
        ).exists()
        has_pending_followup = Task.objects.filter(
            task_type=Task.TaskType.FOLLOW_UP,
            status=Task.Status.PENDING,
            payload__public_id=lead.public_identifier,
        ).exists()
        has_send_task = Task.objects.filter(
            task_type=Task.TaskType.SEND_MESSAGE,
            status__in=[Task.Status.PENDING, Task.Status.RUNNING],
            payload__public_id=lead.public_identifier,
        ).exists()

        if has_draft or has_pending_followup or has_send_task:
            skipped += 1
            continue

        enqueue_follow_up(
            deal.campaign_id,
            lead.public_identifier,
            delay_seconds=_random.uniform(5, 30),
            deal=deal,
        )
        enqueued += 1

    return JsonResponse({"ok": True, "enqueued": enqueued, "skipped": skipped})


@login_required
@require_GET
def api_google_status(request):
    google = {"connected": False, "email": "", "scopes": []}
    try:
        from google_integration.models import GoogleAccount

        ga = GoogleAccount.objects.filter(user=request.user).first()
        if ga and ga.is_connected:
            google = {
                "connected": True,
                "email": ga.google_email or "",
                "scopes": ga.scopes or [],
            }
    except Exception:
        pass
    return JsonResponse({"ok": True, "google": google})


@login_required
@require_GET
def api_google_sheets(request):
    from google_integration import services as gs
    from google_integration.models import GoogleAccount
    from linkedin.models import SiteConfig

    ga = GoogleAccount.objects.filter(user=request.user).first()
    if not ga or not ga.is_connected:
        return JsonResponse({"ok": False, "error": "Google account not connected"}, status=400)
    try:
        sheets = gs.list_spreadsheets(ga)
        cfg = SiteConfig.load()
        configured_id = (cfg.google_sheet_id or "").strip()
        # Drive list may omit sheets not created/opened by this app; always surface configured sheet explicitly.
        if configured_id and not any((s.get("id") or "") == configured_id for s in sheets):
            try:
                meta = gs.get_spreadsheet_meta(ga, configured_id)
                sheets.insert(
                    0,
                    {
                        "id": configured_id,
                        "name": meta.get("properties", {}).get("title", "Configured sheet"),
                        "modifiedTime": "",
                        "webViewLink": meta.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{configured_id}/edit"),
                        "isConfiguredSheet": True,
                    },
                )
            except Exception:
                # Keep list available even if configured sheet is inaccessible or invalid.
                sheets.insert(
                    0,
                    {
                        "id": configured_id,
                        "name": "Configured sheet (unavailable)",
                        "modifiedTime": "",
                        "webViewLink": f"https://docs.google.com/spreadsheets/d/{configured_id}/edit",
                        "isConfiguredSheet": True,
                    },
                )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    items = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "modifiedTime": s.get("modifiedTime"),
            "webViewLink": s.get("webViewLink"),
            "isConfiguredSheet": bool(s.get("isConfiguredSheet")),
        }
        for s in sheets
    ]
    return JsonResponse({"ok": True, "items": items})


@login_required
@require_http_methods(["POST"])
def api_message_drafts_approve(request):
    import json
    from django.utils import timezone

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload"}, status=400)

    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return JsonResponse({"ok": False, "error": "ids[] is required"}, status=400)

    drafts = ChatMessage.objects.filter(pk__in=ids, is_draft=True, is_approved=False)
    approved = 0
    for draft in drafts:
        draft.is_approved = True
        draft.is_draft = False
        draft.save(update_fields=["is_approved", "is_draft"])

        public_id = ""
        campaign_id = draft.campaign_id
        deal = None
        obj = draft.content_object
        if obj and obj.__class__.__name__ == "Lead":
            public_id = obj.public_identifier
            deal = obj.deal_set.filter(campaign_id=campaign_id).first() if campaign_id else obj.deal_set.first()
            if deal and not campaign_id:
                campaign_id = deal.campaign_id

        if public_id and campaign_id:
            Task.objects.create(
                task_type=Task.TaskType.SEND_MESSAGE,
                status=Task.Status.PENDING,
                scheduled_at=timezone.now(),
                deal=deal,
                payload={"message_id": draft.pk, "public_id": public_id, "campaign_id": campaign_id},
            )
            approved += 1

    return JsonResponse({"ok": True, "approved": approved})
