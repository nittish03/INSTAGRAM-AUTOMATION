from django.apps import AppConfig


class CrmConfig(AppConfig):
    name = "crm"
    label = "crm"
    default_auto_field = "django.db.models.AutoField"

    def ready(self) -> None:
        import crm.signals  # noqa: F401
