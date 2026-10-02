from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.urls import reverse

from .models import Usuario


class UsuarioCriacaoForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("username", "first_name", "last_name", "email", "perfil")


class UsuarioEdicaoForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = "__all__"


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    form = UsuarioEdicaoForm
    add_form = UsuarioCriacaoForm
    list_display = ("username", "first_name", "last_name", "email", "perfil", "is_staff", "is_active")
    list_display_links = ("username",)
    change_form_template = "admin/usuarios/usuario/change_form.html"
    actions = ("desativar_acesso",)
    readonly_fields = ("termos_aceitos_versao", "termos_aceitos_em")
    list_filter = ("perfil", "is_staff", "is_superuser", "is_active")
    search_fields = ("first_name", "last_name", "email", "username")
    ordering = ("first_name", "username")
    fieldsets = UserAdmin.fieldsets + (
        ("Sistema", {"fields": ("perfil",)}),
        ("Aceite dos termos", {"fields": ("termos_aceitos_versao", "termos_aceitos_em")}),
    )

    @admin.action(description="Desativar acesso dos usuários selecionados", permissions=["change"])
    def desativar_acesso(self, request, queryset):
        quantidade = queryset.update(is_active=False)
        self.message_user(request, f"Acesso desativado para {quantidade} usuário(s).")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        usuario = self.get_object(request, object_id)
        if usuario is not None and self.has_change_permission(request, usuario):
            extra_context["trocar_senha_url"] = reverse(
                f"{self.admin_site.name}:auth_user_password_change", args=[usuario.pk]
            )
        return super().change_view(request, object_id, form_url, extra_context)
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "username",
                    "perfil",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
