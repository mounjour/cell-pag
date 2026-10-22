from django.urls import path

from . import views

app_name = "assistente"

urlpatterns = [
    path("desktop/", views.AcessoDesktopView.as_view(), name="desktop"),
    path("desktop/conector/", views.ConectorDownloadView.as_view(), name="conector"),
    path("desktop/<int:pk>/revogar/", views.RevogarAcessoView.as_view(), name="revogar"),
    path("desktop/instalador/", views.InstaladorDownloadView.as_view(), name="instalador"),
    path("desktop/<int:pk>/instalador-novo/", views.RenovarInstaladorView.as_view(), name="instalador_novo"),
    path("desktop/instrucoes/", views.InstrucoesColadasView.as_view(), name="instrucoes_coladas"),
    path("api/conector.py", views.ArquivoApiView.as_view(), {"arquivo": "conector.py"}, name="api_conector"),
    path("api/instalador.py", views.ArquivoApiView.as_view(), {"arquivo": "instalador.py"}, name="api_instalador"),
    path("api/ferramentas/", views.FerramentasApiView.as_view(), name="api_ferramentas"),
    path("api/executar/", views.ExecutarApiView.as_view(), name="api_executar"),
]
