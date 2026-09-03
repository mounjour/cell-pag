"""Modelos de Pagamento (Fase 2 em diante).

**Fase 2 — implementado:** ``Vencimento`` (a parcela gerada a partir da
estrutura do contrato). A geração fica em ``Contrato.gerar_vencimentos`` +
``manage.py gerar_vencimentos``; a recorrência de datas em
``apps.pagamentos.recorrencia``.

**Fase 3 — ainda esqueleto:** ``Pagamento`` e ``Cobranca``. Regras já conhecidas
(PLANO-DO-PROJETO.md, seções 5, 6, 8 e 10):

* ``Pagamento`` -> contrato, vencimento?, data_pagamento, valor_pago, forma,
  usuario_baixa, comprovante?, tipo(total/parcial), observacao;
* pagamento parcial (Q16) é aceito — o saldo soma no próximo pagamento do contrato;
* ``UniqueConstraint(contrato, vencimento)`` no ``Pagamento`` (anti cobrança
  duplicada) + checagem na tela + trilha via django-auditlog;
* ``Cobranca`` -> contrato, data_alvo, canal(whatsapp/lembrete),
  status(pendente/enviado/erro), mensagem, enviado_em.
"""

from decimal import Decimal

from django.db import models


class Vencimento(models.Model):
    """Uma parcela do contrato: quando vence e quanto se espera receber.

    Gerada em lote pelo job diário (``manage.py gerar_vencimentos``) a partir de
    ``contrato.data_inicio`` + estrutura + ``valor_parcela``. O vínculo com o
    ``Pagamento`` e a baixa (total/parcial) entram na Fase 3 — por ora
    ``valor_pago`` fica em 0 e ``status`` em "aberto".
    """

    class Status(models.TextChoices):
        ABERTO = "aberto", "Em aberto"
        PARCIAL = "parcial", "Parcial"
        PAGO = "pago", "Pago"

    contrato = models.ForeignKey(
        "contratos.Contrato",
        on_delete=models.CASCADE,
        related_name="vencimentos",
        verbose_name="contrato",
    )
    numero = models.PositiveIntegerField("nº da parcela")
    data_vencimento = models.DateField("data de vencimento")
    valor_previsto = models.DecimalField("valor previsto", max_digits=10, decimal_places=2)
    valor_pago = models.DecimalField(
        "valor pago", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTO
    )

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "vencimento"
        verbose_name_plural = "vencimentos"
        ordering = ["contrato", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["contrato", "numero"],
                name="vencimento_unico_por_contrato",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contrato} — parcela {self.numero}"

    @property
    def saldo(self) -> Decimal:
        """Quanto ainda falta receber desta parcela."""
        return self.valor_previsto - self.valor_pago

    @property
    def quitada(self) -> bool:
        return self.status == self.Status.PAGO
