from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Formulário de login padrão do Django, só com o rótulo mais claro: o
    campo aceita o nome de usuário OU o e-mail cadastrado (ver
    ``apps.usuarios.backends.UsuarioOuEmailBackend``)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuário ou e-mail"
        self.fields["username"].widget.attrs["autocomplete"] = "username"
