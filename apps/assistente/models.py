"""Acesso do Claude Desktop ao sistema: a chave de cada pessoa e o registro de tudo o que foi feito por ela."""

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _hash(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


class AcessoApi(models.Model):
    """Chave de acesso de uma pessoa para o conector do Claude Desktop. Só o resumo (hash) é guardado."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="acessos_api")
    nome = models.CharField("nome", max_length=60, help_text="Ex.: Notebook da Yslane")
    chave_hash = models.CharField(max_length=64, unique=True, editable=False)
    final_da_chave = models.CharField(max_length=6, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    ultimo_uso = models.DateTimeField(null=True, blank=True)
    instalador_baixado_em = models.DateTimeField(null=True, blank=True)  # passo 2 feito
    instrucoes_coladas_em = models.DateTimeField(null=True, blank=True)  # passo 4 feito (marcado pela pessoa)
    revogado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "acesso do Claude Desktop"
        verbose_name_plural = "acessos do Claude Desktop"

    def __str__(self) -> str:
        return f"{self.nome} ({self.usuario})"

    @property
    def ativo(self) -> bool:
        return self.revogado_em is None

    @classmethod
    def criar(cls, usuario, nome: str) -> tuple["AcessoApi", str]:
        """Cria o acesso e devolve (acesso, chave em texto). A chave só existe neste momento."""
        chave = "cp_" + secrets.token_urlsafe(32)
        acesso = cls.objects.create(usuario=usuario, nome=nome[:60], chave_hash=_hash(chave), final_da_chave=chave[-4:])
        return acesso, chave

    @classmethod
    def por_chave(cls, chave: str) -> "AcessoApi | None":
        if not chave:
            return None
        return cls.objects.select_related("usuario").filter(chave_hash=_hash(chave), revogado_em__isnull=True, usuario__is_active=True).first()

    def renovar(self) -> tuple["AcessoApi", str]:
        """Troca esta chave por uma nova do mesmo computador (mesmo nome) e revoga esta, para não ficarem duas ativas.
        O andamento das instruções do Projeto é herdado: elas não dependem da chave."""
        novo, chave = AcessoApi.criar(self.usuario, self.nome)
        novo.instrucoes_coladas_em = self.instrucoes_coladas_em
        novo.save(update_fields=["instrucoes_coladas_em"])
        self.revogar()
        return novo, chave

    def revogar(self) -> None:
        self.revogado_em = timezone.now()
        self.save(update_fields=["revogado_em"])


class OperacaoApi(models.Model):
    """Registro de cada ferramenta usada pelo Claude Desktop (quem, quando, o quê e o resultado)."""

    acesso = models.ForeignKey(AcessoApi, on_delete=models.SET_NULL, null=True, related_name="operacoes")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    ferramenta = models.CharField(max_length=40)
    grava = models.BooleanField(default=False)
    parametros = models.JSONField(default=dict)
    resumo = models.TextField(blank=True)
    ok = models.BooleanField(default=True)
    resultado = models.TextField(blank=True)
    referencias = models.JSONField(default=dict, blank=True)  # ex.: {"pagamento_id": 7}, para poder desfazer
    desfeita_em = models.DateTimeField(null=True, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criada_em"]
        verbose_name = "operação do Claude Desktop"
        verbose_name_plural = "operações do Claude Desktop"

    def __str__(self) -> str:
        return f"{self.ferramenta} · {'ok' if self.ok else 'erro'}"
