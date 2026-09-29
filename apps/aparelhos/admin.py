from django.contrib import admin

from .models import Aparelho


@admin.register(Aparelho)
class AparelhoAdmin(admin.ModelAdmin):
    list_display = ("modelo", "imei", "status_label", "custo", "fornecedor", "criado_em")
    list_filter = ("fornecedor",)
    search_fields = ("modelo", "imei")
    readonly_fields = ("criado_em", "atualizado_em")

    @admin.display(description="status")
    def status_label(self, obj: Aparelho) -> str:
        return obj.status_label
