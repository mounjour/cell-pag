from django.contrib import admin

from .models import Contrato, DocumentoContrato


class DocumentoContratoInline(admin.TabularInline):
    model = DocumentoContrato
    extra = 0
    fields = ("tipo", "arquivo", "descricao", "enviado_por", "enviado_em")
    readonly_fields = ("enviado_em",)


@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = ("cliente", "apelido", "estrutura", "valor_total", "status", "data_inicio")
    list_filter = ("estrutura", "status")
    search_fields = ("cliente__nome", "cliente__cpf", "apelido", "aparelho_modelo", "imei")
    autocomplete_fields = ("cliente",)
    readonly_fields = ("criado_em", "atualizado_em")
    inlines = [DocumentoContratoInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, DocumentoContrato) and obj.enviado_por_id is None:
                obj.enviado_por = request.user
            obj.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()
