from django.urls import path

from . import views
from .webhooks import WhatsAppWebhookView

app_name = "pagamentos"

urlpatterns = [
    path("cobrar-hoje/", views.CobrarHojeView.as_view(), name="cobrar_hoje"),
    path("historico/", views.HistoricoPagamentosView.as_view(), name="historico"),
    path("webhooks/whatsapp/", WhatsAppWebhookView.as_view(), name="whatsapp_webhook"),
    path(
        "contrato/<int:contrato_pk>/novo/",
        views.PagamentoCreateView.as_view(),
        name="novo",
    ),
    path(
        "contrato/<int:contrato_pk>/<int:pk>/estornar/",
        views.PagamentoEstornarView.as_view(),
        name="estornar",
    ),
]
