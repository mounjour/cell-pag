from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Formulário de login padrão do Django, com o rótulo mais claro (o
    campo aceita o nome de usuário OU o e-mail cadastrado — ver
    ``apps.usuarios.backends.UsuarioOuEmailBackend``) e a opção de manter
    a sessão aberta por mais tempo."""

    manter_conectado = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuário ou e-mail"
        self.fields["username"].widget.attrs["autocomplete"] = "username"
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"
        self.fields["manter_conectado"].label = (
            f"Manter conectado por {settings.SESSION_MANTER_CONECTADO_DIAS} dias"
        )
