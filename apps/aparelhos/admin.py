from django.contrib import admin

from .models import Aparelho, BloqueioAparelho


@admin.register(Aparelho)
class AparelhoAdmin(admin.ModelAdmin):
    list_display = ("modelo", "imei", "status_label", "custo", "fornecedor", "criado_em")
    list_filter = ("fornecedor",)
    search_fields = ("modelo", "imei")
    readonly_fields = ("criado_em", "atualizado_em")

    @admin.display(description="status")
    def status_label(self, obj: Aparelho) -> str:
        return obj.status_label


@admin.register(BloqueioAparelho)
class BloqueioAparelhoAdmin(admin.ModelAdmin):
    list_display = ("contrato", "bloqueado_em", "bloqueado_por", "desbloqueado_em", "desbloqueado_por")
    list_filter = ("desbloqueado_em",)
    search_fields = ("contrato__apelido", "contrato__cliente__nome")
    readonly_fields = ("bloqueado_em", "desbloqueado_em")
