"""Google Account integration models.

Stores per-user Google OAuth tokens (encrypted at rest) so the app can
make Sheets API calls on behalf of the user without re-auth on every action.
"""
from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from linkedin.models import decrypt_value, encrypt_value

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


class GoogleAccount(models.Model):
    """Per-user Google OAuth credentials (encrypted)."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="google_account",
    )
    google_email = models.EmailField(blank=True, default="")
    google_sub = models.CharField(max_length=128, blank=True, default="")
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expiry = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Google Account"
        verbose_name_plural = "Google Accounts"

    def __str__(self) -> str:
        return f"{self.user.username} → {self.google_email or '(unlinked)'}"

    # ------------------------------------------------------------------
    # Encryption hooks (mirrors InstagramProfile pattern)
    # ------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.access_token and self.access_token.startswith("gAAAA"):
            self.access_token = decrypt_value(self.access_token)
        if self.refresh_token and self.refresh_token.startswith("gAAAA"):
            self.refresh_token = decrypt_value(self.refresh_token)

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        if self.access_token and self.access_token.startswith("gAAAA"):
            self.access_token = decrypt_value(self.access_token)
        if self.refresh_token and self.refresh_token.startswith("gAAAA"):
            self.refresh_token = decrypt_value(self.refresh_token)

    def save(self, *args, **kwargs):
        plain_access = self.access_token
        plain_refresh = self.refresh_token
        if self.access_token and not self.access_token.startswith("gAAAA"):
            self.access_token = encrypt_value(self.access_token)
        if self.refresh_token and not self.refresh_token.startswith("gAAAA"):
            self.refresh_token = encrypt_value(self.refresh_token)
        super().save(*args, **kwargs)
        self.access_token = plain_access
        self.refresh_token = plain_refresh

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return bool(self.refresh_token)

    @property
    def is_token_expired(self) -> bool:
        if not self.token_expiry:
            return True
        return timezone.now() >= (self.token_expiry - timedelta(seconds=60))

    def to_credentials_dict(self) -> dict:
        return {
            "token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": getattr(settings, "GOOGLE_CLIENT_ID", ""),
            "client_secret": getattr(settings, "GOOGLE_CLIENT_SECRET", ""),
            "scopes": self.scopes or GOOGLE_SCOPES,
        }

    def update_from_credentials(self, creds) -> None:
        """Update fields from a `google.oauth2.credentials.Credentials` object."""
        self.access_token = creds.token or ""
        if getattr(creds, "refresh_token", None):
            self.refresh_token = creds.refresh_token
        if getattr(creds, "expiry", None):
            expiry = creds.expiry
            if timezone.is_naive(expiry):
                expiry = timezone.make_aware(expiry, dt_timezone.utc)
            self.token_expiry = expiry
        if getattr(creds, "scopes", None):
            self.scopes = list(creds.scopes)
