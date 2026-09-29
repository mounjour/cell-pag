from django.apps import AppConfig


class AparelhosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.aparelhos"
    verbose_name = "Aparelhos"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import Aparelho

        auditlog.register(Aparelho)
