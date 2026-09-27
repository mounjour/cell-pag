from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Usuario(AbstractUser):
    """Usuário do sistema.

    Modelo de usuário customizado desde o início do projeto para evitar migração
    dolorosa depois. Por enquanto só acrescenta `perfil` ao usuário padrão do
    Django; o restante (nome, e-mail, senha, permissões) vem de `AbstractUser`.
    """

    class Perfil(models.TextChoices):
        FINANCEIRO = "financeiro", "Financeiro"
        DONO = "dono", "Dono"

    # Nome e e-mail são obrigatórios (o Django deixa ambos em branco por
    # padrão): o nome é o que aparece dentro do sistema e o e-mail serve para
    # entrar e para recuperar a senha.
    first_name = models.CharField("nome", max_length=150)
    email = models.EmailField("e-mail")

    REQUIRED_FIELDS = ["first_name", "email"]

    class Tema(models.TextChoices):
        CLARO = "claro", "Claro"
        ESCURO = "escuro", "Escuro"

    # Preferência de aparência, guardada na conta (vale em qualquer aparelho).
    tema = models.CharField(
        "tema", max_length=10, choices=Tema.choices, default=Tema.CLARO
    )

    perfil = models.CharField(
        "perfil",
        max_length=20,
        choices=Perfil.choices,
        default=Perfil.FINANCEIRO,
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.nome_completo

    @property
    def nome_completo(self) -> str:
        """Nome (e sobrenome, se houver). Cai no login só para contas antigas
        que ainda não têm nome cadastrado."""
        return self.get_full_name() or self.username

    @property
    def nome_curto(self) -> str:
        """Só o primeiro nome — para a barra do sistema, onde falta espaço."""
        return self.first_name or self.username

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()
        if (
            self.email
            and Usuario.objects.filter(email__iexact=self.email)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError({"email": "Já existe um usuário com este e-mail."})

    @property
    def is_dono(self) -> bool:
        """Perfil dono (ou superusuário). Vê tudo que o financeiro vê e mais."""
        return self.is_superuser or self.perfil == self.Perfil.DONO

    @property
    def is_financeiro(self) -> bool:
        return self.perfil == self.Perfil.FINANCEIRO
