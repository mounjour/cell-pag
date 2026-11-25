from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    AjudaView,
    CadastroConviteView,
    ConvitesView,
    LoginView,
    TermosView,
    convite_cancelar,
    salvar_tema,
    termos_aceitar,
)

app_name = "usuarios"

urlpatterns = [
    path("entrar/", LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("cadastro/", CadastroConviteView.as_view(), name="cadastro"),
    path("cadastro/<str:codigo>/", CadastroConviteView.as_view(), name="cadastro_codigo"),
    path("convites/", ConvitesView.as_view(), name="convites"),
    path("convites/<int:pk>/cancelar/", convite_cancelar, name="convite_cancelar"),
    path("tema/", salvar_tema, name="tema"),
    path("ajuda/", AjudaView.as_view(), name="ajuda"),
    path("termos/", TermosView.as_view(), name="termos"),
    path("termos/aceitar/", termos_aceitar, name="termos_aceitar"),
]
