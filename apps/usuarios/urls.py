from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .views import LoginView, SenhaAlterarView, TermosView, salvar_tema, termos_aceitar

app_name = "usuarios"

urlpatterns = [
    path("entrar/", LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("tema/", salvar_tema, name="tema"),
    path("senha/alterar/", SenhaAlterarView.as_view(), name="senha_alterar"),
    path("termos/", TermosView.as_view(), name="termos"),
    path("termos/aceitar/", termos_aceitar, name="termos_aceitar"),
    # Recuperação de senha por e-mail. A resposta é a mesma exista ou não a
    # conta (o Django não revela se o e-mail está cadastrado).
    path(
        "senha/esqueci/",
        auth_views.PasswordResetView.as_view(
            template_name="usuarios/senha_esqueci.html",
            email_template_name="usuarios/email/senha_redefinir.txt",
            subject_template_name="usuarios/email/senha_redefinir_assunto.txt",
            success_url=reverse_lazy("usuarios:senha_esqueci_enviado"),
        ),
        name="senha_esqueci",
    ),
    path(
        "senha/esqueci/enviado/",
        auth_views.PasswordResetDoneView.as_view(template_name="usuarios/senha_esqueci_enviado.html"),
        name="senha_esqueci_enviado",
    ),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="usuarios/senha_redefinir.html",
            success_url=reverse_lazy("usuarios:senha_redefinida"),
        ),
        name="senha_redefinir",
    ),
    path(
        "senha/redefinida/",
        auth_views.PasswordResetCompleteView.as_view(template_name="usuarios/senha_redefinida.html"),
        name="senha_redefinida",
    ),
]
