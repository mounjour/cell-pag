from django.contrib import admin

from .models import Cobranca, Pagamento, Vencimento


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


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = (
        "contrato",
        "vencimento",
        "data_pagamento",
        "valor_pago",
        "forma",
        "usuario_baixa",
        "criado_em",
    )
    list_filter = ("forma", "data_pagamento", "contrato__estrutura")
    search_fields = (
        "contrato__apelido",
        "contrato__cliente__nome",
        "contrato__cliente__cpf",
    )
    autocomplete_fields = ("contrato", "vencimento")
    readonly_fields = ("criado_em",)
    date_hierarchy = "data_pagamento"

    def save_model(self, request, obj, form, change):
        if obj.usuario_baixa_id is None:
            obj.usuario_baixa = request.user
        if change:
            super().save_model(request, obj, form, change)
        else:
            # Baixa nova: reflete na parcela (status + transporte de saldo).
            obj.registrar()


@admin.register(Cobranca)
class CobrancaAdmin(admin.ModelAdmin):
    list_display = (
        "data_alvo",
        "contrato",
        "destinatario",
        "status",
        "tentativas",
        "enviado_em",
    )
    list_filter = ("status", "canal", "data_alvo")
    search_fields = (
        "contrato__cliente__nome",
        "contrato__cliente__cpf",
        "destinatario",
        "id_externo",
    )
    readonly_fields = (
        "id_externo",
        "tentativas",
        "enviado_em",
        "entregue_em",
        "lido_em",
        "criado_em",
        "atualizado_em",
    )
    date_hierarchy = "data_alvo"
