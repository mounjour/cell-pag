from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "cpf", "telefone_whatsapp", "criado_em")
    search_fields = ("nome", "cpf", "telefone_whatsapp")
    readonly_fields = ("criado_em", "atualizado_em")
