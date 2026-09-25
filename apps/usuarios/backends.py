"""Login por usuário OU e-mail — pedido do Alisson (facilita pra Yslane)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsuarioOuEmailBackend(ModelBackend):
    """Igual ao ``ModelBackend`` padrão, só que aceita o *username* OU o
    e-mail cadastrado no campo "usuário" do login.

    Sem e-mail único garantido no banco (``Usuario.email`` não tem
    ``unique=True``), então em caso de mais de um usuário com o mesmo e-mail
    pega o mais antigo — situação rara com só duas contas neste sistema.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        UserModel = get_user_model()
        candidatos = UserModel.objects.filter(
            Q(**{f"{UserModel.USERNAME_FIELD}__iexact": username}) | Q(email__iexact=username)
        ).order_by("pk")
        usuario = candidatos.first()
        if usuario is None:
            # Mesmo custo de hash de um check_password real — mitiga inferir
            # por tempo de resposta se o usuário/e-mail existe (padrão do
            # próprio ModelBackend do Django).
            UserModel().set_password(password)
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
