from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="clientes:lista", permanent=False)),
    path("", include("apps.usuarios.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("contratos/", include("apps.contratos.urls")),
    path("pagamentos/", include("apps.pagamentos.urls")),
    path("relatorios/", include("apps.relatorios.urls")),
    # compat: o link antigo /cobrar-hoje/ segue funcionando
    path(
        "cobrar-hoje/",
        RedirectView.as_view(pattern_name="pagamentos:cobrar_hoje", permanent=False),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Acompanhamento de Pagamentos"
admin.site.site_title = "Acompanhamento de Pagamentos"
admin.site.index_title = "Administração"
