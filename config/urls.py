from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Provisório: a raiz leva ao admin até existir uma interface própria (Fase 2).
    path("", RedirectView.as_view(pattern_name="admin:index", permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Acompanhamento de Pagamentos"
admin.site.site_title = "Acompanhamento de Pagamentos"
admin.site.index_title = "Administração"
