from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="relatorios:inicio", permanent=False)),
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

# Mídia (comprovantes, documentos) NÃO é servida por URL pública — só pelas
# views autenticadas pagamentos:comprovante / contratos:documento_baixar.

admin.site.site_header = "Acompanhamento de Pagamentos"
admin.site.site_title = "Acompanhamento de Pagamentos"
admin.site.index_title = "Administração"
