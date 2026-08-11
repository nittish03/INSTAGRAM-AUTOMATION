"""Unfold admin sidebar: direct changelist links (no app-index hop)."""

from __future__ import annotations

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


def unfold_sidebar_navigation(request):
    """Return sidebar groups; callable so Unfold can pass ``request``."""
    return _SIDEBAR_GROUPS


_SIDEBAR_GROUPS = [
    {
        "title": _("Dashboard"),
        "separator": True,
        "items": [
            {
                "title": _("Home"),
                "icon": "dashboard",
                "link": reverse_lazy("admin:index"),
            },
            {
                "title": _("Analytics"),
                "icon": "bar_chart",
                "link": reverse_lazy("analytics_dashboard"),
            },
        ],
    },
    {
        "title": _("Instagram"),
        "separator": True,
        "items": [
            {
                "title": _("Action logs"),
                "icon": "history",
                "link": reverse_lazy("admin:linkedin_actionlog_changelist"),
            },
            {
                "title": _("Campaigns"),
                "icon": "hub",
                "link": reverse_lazy("admin:linkedin_campaign_changelist"),
            },
            {
                "title": _("Instagram profiles"),
                "icon": "person",
                "link": reverse_lazy("admin:linkedin_instagramprofile_changelist"),
            },
            {
                "title": _("Search keywords"),
                "icon": "search",
                "link": reverse_lazy("admin:linkedin_searchkeyword_changelist"),
            },
            {
                "title": _("Site configuration"),
                "icon": "tune",
                "link": reverse_lazy("admin:linkedin_siteconfig_changelist"),
            },
            {
                "title": _("Tasks"),
                "icon": "task_alt",
                "link": reverse_lazy("admin:linkedin_task_changelist"),
            },
        ],
    },
    {
        "title": _("CRM"),
        "separator": True,
        "items": [
            {
                "title": _("Leads"),
                "icon": "person_search",
                "link": reverse_lazy("admin:crm_lead_changelist"),
            },
            {
                "title": _("Deals"),
                "icon": "handshake",
                "link": reverse_lazy("admin:crm_deal_changelist"),
            },
        ],
    },
    {
        "title": _("Chat"),
        "separator": True,
        "items": [
            {
                "title": _("Messages"),
                "icon": "chat",
                "link": reverse_lazy("admin:chat_chatmessage_changelist"),
            },
        ],
    },
    {
        "title": _("Google"),
        "separator": True,
        "items": [
            {
                "title": _("Google Workspace"),
                "icon": "table_chart",
                "link": "/admin/google/",
            },
        ],
    },
]
