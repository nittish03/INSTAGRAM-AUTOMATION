# linkedin/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from linkedin import analytics_views, views

urlpatterns = [
    path("api/csrf/", views.api_csrf, name="api_csrf"),
    path("api/auth/login/", views.api_login, name="api_login"),
    path("api/auth/logout/", views.api_logout, name="api_logout"),
    path("api/auth/me/", views.api_me, name="api_me"),
    path("api/dashboard/", views.api_dashboard, name="api_dashboard"),
    path("api/campaigns/", views.api_campaigns, name="api_campaigns"),
    path("api/campaigns/<int:campaign_id>/", views.api_campaign_detail, name="api_campaign_detail"),
    path("api/leads/", views.api_leads, name="api_leads"),
    path("api/deals/", views.api_deals, name="api_deals"),
    path("api/tasks/", views.api_tasks, name="api_tasks"),
    path("api/messages/drafts/", views.api_message_drafts, name="api_message_drafts"),
    path("api/messages/drafts/approve/", views.api_message_drafts_approve, name="api_message_drafts_approve"),
    path("api/messages/drafts/<int:draft_id>/", views.api_message_draft_detail, name="api_message_draft_detail"),
    path("api/messaging/diagnostics/", views.api_messaging_diagnostics, name="api_messaging_diagnostics"),
    path("api/messaging/heal/", views.api_messaging_heal, name="api_messaging_heal"),
    path("api/action-logs/", views.api_action_logs, name="api_action_logs"),
    path("api/linkedin-profiles/", views.api_linkedin_profiles, name="api_linkedin_profiles"),
    path("api/linkedin-profiles/<int:profile_id>/toggle/", views.api_linkedin_profile_toggle, name="api_linkedin_profile_toggle"),
    path("api/search-keywords/", views.api_search_keywords, name="api_search_keywords"),
    path("api/search-keywords/create/", views.api_search_keywords_create, name="api_search_keywords_create"),
    path("api/search-keywords/<int:keyword_id>/", views.api_search_keywords_delete, name="api_search_keywords_delete"),
    path("api/site-config/", views.api_site_config, name="api_site_config"),
    path("api/site-config/save/", views.api_site_config_save, name="api_site_config_save"),
    path("api/analytics/", views.api_analytics, name="api_analytics"),
    path("api/google/status/", views.api_google_status, name="api_google_status"),
    path("api/google/sheets/", views.api_google_sheets, name="api_google_sheets"),
    path("api/google/disconnect/", views.api_google_disconnect, name="api_google_disconnect"),
    path("api/workbench/", views.api_workbench, name="api_workbench"),
    path("api/leads/<int:lead_id>/insights/", views.api_lead_insights, name="api_lead_insights"),
    path("api/leads/<int:lead_id>/timeline/", views.api_lead_timeline, name="api_lead_timeline"),
    path("api/campaign-health/", views.api_campaign_health, name="api_campaign_health"),
    path("api/recovery/", views.api_recovery, name="api_recovery"),
    path("api/tasks/<int:task_id>/retry/", views.api_task_retry, name="api_task_retry"),
    path("api/tasks/bulk-retry/", views.api_tasks_bulk_retry, name="api_tasks_bulk_retry"),
    path("api/export-preview/", views.api_export_preview, name="api_export_preview"),
    path("api/export-selected/", views.api_export_selected, name="api_export_selected"),
    path("api/follow-up-suggestions/", views.api_followup_suggestions, name="api_followup_suggestions"),
    path("api/follow-ups/queue/", views.api_followups_queue, name="api_followups_queue"),
    path("api/safe-mode/", views.api_safe_mode, name="api_safe_mode"),
    path("admin/analytics/", analytics_views.analytics_dashboard, name="analytics_dashboard"),
    path("admin/google/", include("google_integration.urls", namespace="google_integration")),
    # App index pages list the same models as the sidebar; send bookmarks/old links to dashboard.
    path(
        "admin/linkedin/",
        RedirectView.as_view(url="/admin/", permanent=False),
    ),
    path(
        "admin/crm/",
        RedirectView.as_view(url="/admin/", permanent=False),
    ),
    path(
        "admin/chat/",
        RedirectView.as_view(url="/admin/", permanent=False),
    ),
    path("admin/", admin.site.urls),
    # Backward-compatible redirects for older links/bookmarks.
    path("google/", RedirectView.as_view(url="/admin/google/", permanent=False)),
    path("google/<path:subpath>", RedirectView.as_view(url="/admin/google/%(subpath)s", permanent=False)),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
