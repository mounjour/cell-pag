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


class CadastroPorConviteForm(forms.Form):
    """Cadastro do convidado: nome, e-mail e senha. O e-mail também é o login
    (a tela de entrada aceita usuário ou e-mail) e o perfil vem do convite."""

    nome = forms.CharField(label="Nome", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(
        label="E-mail (será o seu login)", widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    senha = forms.CharField(
        label="Senha", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    senha2 = forms.CharField(
        label="Repita a senha", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    aceito = forms.BooleanField(
        label="Li e aceito os Termos de uso e privacidade",
        error_messages={"required": "Para criar o usuário, aceite os Termos de uso e privacidade."},
    )

    def clean_nome(self):
        return " ".join(self.cleaned_data["nome"].split())

    def clean_email(self):
        from .models import Usuario

        email = self.cleaned_data["email"].strip().lower()
        if (
            Usuario.objects.filter(email__iexact=email).exists()
            or Usuario.objects.filter(username__iexact=email).exists()
        ):
            raise forms.ValidationError("Já existe um usuário com este e-mail.")
        return email

    def clean(self):
        from django.contrib.auth.password_validation import validate_password

        from .models import Usuario

        dados = super().clean()
        senha, senha2 = dados.get("senha"), dados.get("senha2")
        if senha and senha2 and senha != senha2:
            self.add_error("senha2", "As duas senhas não são iguais.")
        elif senha:
            candidato = Usuario(
                username=dados.get("email", ""), first_name=dados.get("nome", ""), email=dados.get("email", "")
            )
            try:
                validate_password(senha, candidato)
            except forms.ValidationError as erro:
                self.add_error("senha", erro)
        return dados
