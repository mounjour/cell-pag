from django.apps import AppConfig


class PagamentosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pagamentos"
    verbose_name = "Pagamentos"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import Cobranca, CobrancaCora, EventoCora, Pagamento, Vencimento

        auditlog.register(Vencimento)
        auditlog.register(Pagamento)
        auditlog.register(Cobranca)
        auditlog.register(CobrancaCora)
        auditlog.register(EventoCora)

        # O contador de "Cobrar hoje" no menu depende destes dados.
        from django.db.models.signals import post_delete, post_save

        from apps.contratos.models import Contrato

        from .badge import invalidar

        for modelo in (Pagamento, Vencimento, Contrato):
            post_save.connect(invalidar, sender=modelo, dispatch_uid=f"badge_{modelo.__name__}_save")
            post_delete.connect(invalidar, sender=modelo, dispatch_uid=f"badge_{modelo.__name__}_del")
