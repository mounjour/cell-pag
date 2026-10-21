"""Conversa com o assistente (Claude) e as ações que ele propôs para gravar no sistema."""

from django.conf import settings
from django.db import models


class Conversa(models.Model):
    """Uma conversa de um usuário com o assistente. ``mensagens`` guarda o histórico no formato da API do Claude."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversas_assistente")
    mensagens = models.JSONField(default=list)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-atualizada_em"]
        verbose_name = "conversa do assistente"
        verbose_name_plural = "conversas do assistente"


class Acao(models.Model):
    """Algo que o assistente quer gravar no sistema. Só vale depois que a pessoa confirma com o botão."""

    class Estado(models.TextChoices):
        PENDENTE = "pendente", "Aguardando confirmação"
        CONFIRMADA = "confirmada", "Confirmada"
        CANCELADA = "cancelada", "Cancelada"
        ERRO = "erro", "Não foi possível gravar"

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name="acoes")
    ferramenta = models.CharField(max_length=40)
    parametros = models.JSONField(default=dict)
    resumo = models.TextField()
    avisos = models.JSONField(default=list, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDENTE)
    resultado = models.TextField(blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    decidida_em = models.DateTimeField(null=True, blank=True)
    decidida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["criada_em"]
        verbose_name = "ação do assistente"
        verbose_name_plural = "ações do assistente"

    def __str__(self) -> str:
        return f"{self.ferramenta} · {self.get_estado_display()}"
