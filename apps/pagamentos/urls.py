from django.urls import path

from . import views
from .webhooks import WhatsAppWebhookView
from .cora_webhooks import CoraWebhookView

app_name = "pagamentos"

urlpatterns = [
    path("cobrar-hoje/", views.CobrarHojeView.as_view(), name="cobrar_hoje"),
    path("pix/", views.PixPainelView.as_view(), name="pix_painel"),
    path("historico/", views.HistoricoPagamentosView.as_view(), name="historico"),
    path("webhooks/whatsapp/", WhatsAppWebhookView.as_view(), name="whatsapp_webhook"),
    path("webhooks/cora/", CoraWebhookView.as_view(), name="cora_webhook"),
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
