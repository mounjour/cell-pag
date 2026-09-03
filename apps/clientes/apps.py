from django.apps import AppConfig


class ClientesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clientes"
    verbose_name = "Clientes"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import Cliente

        auditlog.register(Cliente)
