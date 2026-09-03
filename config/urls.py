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
    path("cobrar-hoje/", include("apps.pagamentos.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Acompanhamento de Pagamentos"
admin.site.site_title = "Acompanhamento de Pagamentos"
admin.site.index_title = "Administração"
