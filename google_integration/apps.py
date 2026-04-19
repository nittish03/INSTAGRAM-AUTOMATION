from django.apps import AppConfig


class GoogleIntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "google_integration"
    # Shown in Django metadata only; GoogleAccount is not registered in admin (use /admin/google/).
    verbose_name = "Google Account"
