from django.contrib import admin

from .models import Cobranca, CobrancaPix, EventoCora, Pagamento, Vencimento


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


@admin.register(CobrancaPix)
class CobrancaPixAdmin(admin.ModelAdmin):
    list_display = ("data_vencimento", "vencimento", "valor", "total_pago", "status", "cora_id")
    list_filter = ("status", "data_vencimento")
    search_fields = ("vencimento__contrato__cliente__nome", "cora_id")
    readonly_fields = (
        "idempotency_key", "cora_id", "pix_copia_e_cola", "qr_code_url",
        "total_pago", "pago_em", "criado_em", "atualizado_em",
    )


@admin.register(EventoCora)
class EventoCoraAdmin(admin.ModelAdmin):
    list_display = ("recebido_em", "tipo", "recurso_id", "processado")
    list_filter = ("processado", "tipo")
    search_fields = ("evento_id", "recurso_id")
    readonly_fields = ("evento_id", "tipo", "recurso_id", "processado", "erro", "recebido_em", "processado_em")
