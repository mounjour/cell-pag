from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "email", "perfil", "is_staff")
    list_filter = ("perfil", "is_staff", "is_superuser", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Sistema", {"fields": ("perfil",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Sistema", {"fields": ("perfil",)}),)
