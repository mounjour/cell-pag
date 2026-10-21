from django.urls import path

from . import views

app_name = "assistente"

urlpatterns = [
    path("", views.ChatView.as_view(), name="chat"),
    path("enviar/", views.EnviarView.as_view(), name="enviar"),
    path("nova/", views.NovaConversaView.as_view(), name="nova"),
    path("acao/<int:pk>/confirmar/", views.AcaoConfirmarView.as_view(), name="confirmar"),
    path("acao/<int:pk>/cancelar/", views.AcaoCancelarView.as_view(), name="cancelar"),
]
