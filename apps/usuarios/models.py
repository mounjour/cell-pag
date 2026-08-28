from django.contrib.auth.models import AbstractUser
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
        return self.get_full_name() or self.username
