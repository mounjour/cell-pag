from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

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
    list_display = ("first_name", "last_name", "email", "username", "perfil", "is_staff")
    list_filter = ("perfil", "is_staff", "is_superuser", "is_active")
    search_fields = ("first_name", "last_name", "email", "username")
    ordering = ("first_name", "username")
    fieldsets = UserAdmin.fieldsets + (("Sistema", {"fields": ("perfil",)}),)
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
