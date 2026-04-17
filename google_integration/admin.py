from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import GoogleAccount


@admin.register(GoogleAccount)
class GoogleAccountAdmin(ModelAdmin):
    list_display = ("user", "google_email", "is_connected", "token_expiry", "updated_at")
    readonly_fields = (
        "google_email", "google_sub", "token_expiry", "scopes",
        "created_at", "updated_at",
    )
    fields = (
        "user", "google_email", "google_sub", "token_expiry", "scopes",
        "created_at", "updated_at",
    )
    icon = "link"

    def is_connected(self, obj: GoogleAccount) -> bool:
        return obj.is_connected
    is_connected.boolean = True
    is_connected.short_description = "Connected"

    def has_add_permission(self, request):
        return False
