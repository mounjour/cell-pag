from django.contrib import admin

from .models import Vencimento


@admin.register(Vencimento)
class VencimentoAdmin(admin.ModelAdmin):
    list_display = (
        "contrato",
        "numero",
        "data_vencimento",
        "valor_previsto",
        "valor_pago",
        "status",
    )
    list_filter = ("status", "contrato__estrutura")
    search_fields = (
        "contrato__apelido",
        "contrato__cliente__nome",
        "contrato__cliente__cpf",
    )
    autocomplete_fields = ("contrato",)
    readonly_fields = ("criado_em", "atualizado_em")
    date_hierarchy = "data_vencimento"
