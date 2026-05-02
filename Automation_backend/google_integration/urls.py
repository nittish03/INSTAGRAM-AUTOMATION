"""URL conf intentionally empty.

The Google integration app no longer exposes Django admin OAuth/HTML pages.
All flows are JSON APIs in ``linkedin.views`` (``/api/google/...``) and the
Next.js frontend owns the OAuth redirect at ``/google/callback``.
"""
from django.urls import path

app_name = "google_integration"

urlpatterns: list[path] = []
