from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin

from .models import Cliente


class ClienteResource(resources.ModelResource):
    """Usado para migrar a planilha atual de clientes (import) e para exportar."""

    class Meta:
        model = Cliente
        import_id_fields = ("cpf",)
        fields = ("id", "nome", "cpf", "telefone_whatsapp", "endereco")
        export_order = fields


@admin.register(Cliente)
class ClienteAdmin(ImportExportModelAdmin):
    resource_classes = [ClienteResource]
    list_display = ("nome", "cpf_formatado", "telefone_whatsapp", "criado_em")
    search_fields = ("nome", "cpf", "telefone_whatsapp")
    readonly_fields = ("criado_em", "atualizado_em")
