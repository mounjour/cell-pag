from django.contrib import admin
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from apps.clientes.models import Cliente

from .models import Contrato, DocumentoContrato


class ContratoResource(resources.ModelResource):
    """Export/import de contratos. O cliente é referenciado pelo CPF."""

    cliente = fields.Field(
        column_name="cliente_cpf",
        attribute="cliente",
        widget=ForeignKeyWidget(Cliente, field="cpf"),
    )

    class Meta:
        model = Contrato
        import_id_fields = ("id",)
        fields = (
            "id", "cliente", "apelido", "aparelho_modelo", "imei", "valor_total",
            "estrutura", "valor_parcela", "num_parcelas", "data_inicio",
            "dia_referencia", "fiador", "status", "data_prevista_quitacao",
        )
        export_order = fields


class DocumentoContratoInline(admin.TabularInline):
    model = DocumentoContrato
    extra = 0
    fields = ("tipo", "arquivo", "descricao", "enviado_por", "enviado_em")
    readonly_fields = ("enviado_em",)


@admin.register(Contrato)
class ContratoAdmin(ImportExportModelAdmin):
    resource_classes = [ContratoResource]
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
