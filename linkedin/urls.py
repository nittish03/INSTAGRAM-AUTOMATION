# linkedin/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/google/", include("google_integration.urls", namespace="google_integration")),
    path("admin/", admin.site.urls),
    # Backward-compatible redirects for older links/bookmarks.
    path("google/", RedirectView.as_view(url="/admin/google/", permanent=False)),
    path("google/<path:subpath>", RedirectView.as_view(url="/admin/google/%(subpath)s", permanent=False)),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
