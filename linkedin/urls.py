# linkedin/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from linkedin import analytics_views

urlpatterns = [
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
