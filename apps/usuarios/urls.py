from django.contrib.auth import views as auth_views
from django.urls import path

from .views import LoginView, SenhaAlterarView, TermosView, salvar_tema, termos_aceitar

app_name = "usuarios"

urlpatterns = [
    path("entrar/", LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("tema/", salvar_tema, name="tema"),
    path("senha/alterar/", SenhaAlterarView.as_view(), name="senha_alterar"),
    path("termos/", TermosView.as_view(), name="termos"),
    path("termos/aceitar/", termos_aceitar, name="termos_aceitar"),
]
