from django.urls import path

from . import views

app_name = "assistente"

urlpatterns = [
    path("desktop/", views.AcessoDesktopView.as_view(), name="desktop"),
    path("desktop/conector/", views.ConectorDownloadView.as_view(), name="conector"),
    path("desktop/<int:pk>/revogar/", views.RevogarAcessoView.as_view(), name="revogar"),
    path("api/ferramentas/", views.FerramentasApiView.as_view(), name="api_ferramentas"),
    path("api/executar/", views.ExecutarApiView.as_view(), name="api_executar"),
]
