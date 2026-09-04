from django.apps import AppConfig


class PagamentosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pagamentos"
    verbose_name = "Pagamentos"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import Cobranca, Pagamento, Vencimento

        auditlog.register(Vencimento)
        auditlog.register(Pagamento)
        auditlog.register(Cobranca)
