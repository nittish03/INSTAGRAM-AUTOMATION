"""Google OAuth helpers.

Builds the OAuth2 flow used by the connect/callback views and refreshes
short-lived access tokens transparently for downstream API calls.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from .models import GOOGLE_SCOPES, GoogleAccount

# Users may previously authorize additional Google scopes; allow token responses
# that include supersets of currently requested scopes instead of failing OAuth.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _ensure_oauth_configured() -> None:
    if not getattr(settings, "GOOGLE_CLIENT_ID", None) or not getattr(
        settings, "GOOGLE_CLIENT_SECRET", None
    ):
        raise ImproperlyConfigured(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set "
            "(see .env). Create OAuth credentials in Google Cloud Console."
        )


def build_flow(redirect_uri: str, state: str | None = None) -> Flow:
    _ensure_oauth_configured()
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
        state=state,
        autogenerate_code_verifier=True,
    )
    return flow


def credentials_for(account: GoogleAccount) -> Credentials:
    """Return live `Credentials`, refreshing the access token if needed."""
    _ensure_oauth_configured()
    creds = Credentials(
        token=account.access_token or None,
        refresh_token=account.refresh_token or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=account.scopes or GOOGLE_SCOPES,
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        account.update_from_credentials(creds)
        account.save(update_fields=[
            "access_token", "refresh_token", "token_expiry", "scopes",
        ])
    return creds
