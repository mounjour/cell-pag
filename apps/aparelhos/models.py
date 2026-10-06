"""Estoque de aparelhos — cadastro antes da venda.

Separado do `Contrato` de propósito: o aparelho pode ser comprado (e ficar
"disponível" no estoque) antes de ter um cliente e um plano de parcelas. O
vínculo com o contrato é opcional — quem prefere digitar modelo/IMEI direto
no contrato (fluxo antigo, sem controle de estoque) continua podendo.

``status`` não é um campo salvo: é derivado do ``contrato`` (`Contrato.aparelho`,
`OneToOneField`) — sem isso sincronizar campo e relação poderia divergir (ex.:
contrato apagado sem atualizar o aparelho). Sem contrato: disponível. Com
contrato em andamento: **alocado** (locação). Só vira **vendido** quando o
contrato é quitado.
"""

from django.db import models


class Aparelho(models.Model):
    class Status(models.TextChoices):
        DISPONIVEL = "disponivel", "Disponível"
        ALOCADO = "alocado", "Alocado"
        VENDIDO = "vendido", "Vendido"

    modelo = models.CharField("modelo", max_length=120, help_text='Ex.: "iPhone 11 64GB".')
    imei = models.CharField(
        "IMEI",
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        help_text="15 dígitos. Opcional, mas evita cadastrar o mesmo aparelho duas vezes.",
    )
    custo = models.DecimalField(
        "custo de compra",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Uso interno — não aparece para o cliente nem no contrato.",
    )
    fornecedor = models.CharField("fornecedor", max_length=120, blank=True)
    data_compra = models.DateField("data da compra", null=True, blank=True)
    observacoes = models.TextField("observações", blank=True)

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "aparelho"
        verbose_name_plural = "aparelhos"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"{self.modelo} · IMEI {self.imei}" if self.imei else self.modelo

    def save(self, *args, **kwargs):
        # '' e None são a mesma coisa pra IMEI vazio, mas só None respeita o
        # unique (duas strings vazias contam como duplicata pro Postgres).
        if not self.imei:
            self.imei = None
        super().save(*args, **kwargs)

    @property
    def com_contrato(self) -> bool:
        return hasattr(self, "contrato")

    @property
    def alocado(self) -> bool:
        return self.com_contrato and not self.contrato.quitado

    @property
    def vendido(self) -> bool:
        """Só é vendido quando a locação foi quitada."""
        return self.com_contrato and self.contrato.quitado

    @property
    def status(self) -> str:
        if self.vendido:
            return self.Status.VENDIDO
        if self.alocado:
            return self.Status.ALOCADO
        return self.Status.DISPONIVEL

    @property
    def status_label(self) -> str:
        return self.Status(self.status).label
