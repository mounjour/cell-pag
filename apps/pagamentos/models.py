"""Modelos de Pagamento (Fases 2 e 3).

**Fase 2:** ``Vencimento`` — a parcela gerada a partir da estrutura do contrato.
A geração fica em ``Contrato.gerar_vencimentos`` + ``manage.py gerar_vencimentos``;
a recorrência de datas em ``apps.pagamentos.recorrencia``.

**Fase 3:** ``Pagamento`` — cada baixa recebida é uma linha própria, vinculada a
uma parcela (PLANO-DO-PROJETO.md, seções 4.4 e 6). Regras confirmadas com o
Alisson (03/09 + esta conversa):

* uma linha de ``Pagamento`` por parcela — ``UniqueConstraint(contrato,
  vencimento)`` (anti cobrança duplicada) + checagem na tela + trilha via
  ``django-auditlog``;
* **pagamento parcial** (Q16) é aceito: a parcela fica ``parcial`` e o saldo que
  faltou é **somado ao ``valor_previsto`` da próxima parcela em aberto** (ou fica
  em ``Contrato.saldo_transportado`` se não houver próxima). Pagamento a maior
  faz o caminho inverso (pré-paga a(s) próxima(s));
* a baixa **não** quita o contrato — quitar é ação manual da Yslane
  (``contratos:quitar``);
* a baixa **não** mexe em ``Contrato.proximo_vencimento`` (isso é Fase 4).

``Cobranca`` (registro de notificação) só entra na Fase 6, junto com o envio de
mensagem — não há o que gravar nela antes disso.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Vencimento(models.Model):
    """Uma parcela do contrato: quando vence e quanto se espera receber.

    Gerada em lote pelo job diário (``manage.py gerar_vencimentos``) a partir de
    ``contrato.data_inicio`` + estrutura + ``valor_parcela``. ``valor_pago`` e
    ``status`` passam a mudar na Fase 3, via ``Pagamento.registrar``.
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

    def aplicar_valor_pago(self, novo_total, salvar: bool = True) -> str:
        """Grava ``valor_pago`` e recalcula ``status`` (aberto/parcial/pago).

        Usado pela baixa (``Pagamento.registrar``) e pelo estorno. Devolve o
        novo ``status``.
        """
        self.valor_pago = novo_total
        if novo_total <= 0:
            self.status = self.Status.ABERTO
        elif novo_total < self.valor_previsto:
            self.status = self.Status.PARCIAL
        else:
            self.status = self.Status.PAGO
        if salvar:
            self.save(update_fields=["valor_pago", "status", "atualizado_em"])
        return self.status


def caminho_comprovante(instance: "Pagamento", filename: str) -> str:
    return f"pagamentos/{instance.contrato_id}/{filename}"


class Pagamento(models.Model):
    """Uma baixa recebida, vinculada a uma parcela (nº + data).

    O efeito na parcela e o transporte de saldo do parcial ficam em
    :meth:`registrar` — a view e o admin chamam esse método em vez de ``save``
    direto.
    """

    class Forma(models.TextChoices):
        PIX = "pix", "Pix"
        DINHEIRO = "dinheiro", "Dinheiro"
        OUTRO = "outro", "Outro"

    contrato = models.ForeignKey(
        "contratos.Contrato",
        on_delete=models.PROTECT,
        related_name="pagamentos",
        verbose_name="contrato",
    )
    vencimento = models.ForeignKey(
        Vencimento,
        on_delete=models.PROTECT,
        related_name="pagamentos",
        null=True,
        blank=True,
        verbose_name="parcela",
    )
    data_pagamento = models.DateField("data do pagamento", default=timezone.localdate)
    valor_pago = models.DecimalField("valor pago", max_digits=10, decimal_places=2)
    forma = models.CharField(
        "forma de pagamento", max_length=10, choices=Forma.choices, default=Forma.PIX
    )
    usuario_baixa = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baixas",
        verbose_name="quem deu baixa",
    )
    comprovante = models.FileField(
        "comprovante", upload_to=caminho_comprovante, blank=True
    )
    observacao = models.TextField("observação", blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        ordering = ["-data_pagamento", "-criado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["contrato", "vencimento"],
                condition=models.Q(vencimento__isnull=False),
                name="pagamento_unico_por_vencimento",
            ),
            models.CheckConstraint(
                condition=models.Q(valor_pago__gt=0),
                name="pagamento_valor_positivo",
            ),
        ]

    def __str__(self) -> str:
        alvo = f"parcela {self.vencimento.numero}" if self.vencimento_id else "sem parcela"
        return f"{self.contrato} — {alvo} — R$ {self.valor_pago}"

    def registrar(self) -> None:
        """Salva a baixa e reflete na parcela: ``valor_pago``, ``status`` e o
        transporte do saldo do parcial (ou do troco) para a próxima parcela.

        Idempotente por construção — a ``UniqueConstraint(contrato, vencimento)``
        impede uma segunda baixa na mesma parcela.
        """
        self.save()
        venc = self.vencimento
        if venc is None:
            return

        venc.aplicar_valor_pago(venc.valor_pago + self.valor_pago)
        restante = venc.valor_previsto - venc.valor_pago  # >0 faltou · <0 troco
        if restante:
            self._transportar_saldo(restante)

    def _transportar_saldo(self, restante: Decimal) -> None:
        """Distribui ``restante`` pelas parcelas seguintes em aberto.

        ``restante`` positivo (faltou) entra no ``valor_previsto`` da próxima
        parcela; negativo (troco) abate — cascateando se o troco for maior que a
        parcela. Sem parcela seguinte, sobra em ``Contrato.saldo_transportado``.
        """
        seguintes = (
            self.contrato.vencimentos.filter(numero__gt=self.vencimento.numero)
            .exclude(status=Vencimento.Status.PAGO)
            .order_by("numero")
        )
        for alvo in seguintes:
            novo_valor = alvo.valor_previsto + restante
            if novo_valor < 0:
                alvo.valor_previsto = Decimal("0.00")
                alvo.save(update_fields=["valor_previsto", "atualizado_em"])
                restante = novo_valor
            else:
                alvo.valor_previsto = novo_valor
                alvo.save(update_fields=["valor_previsto", "atualizado_em"])
                restante = Decimal("0.00")
                break
        if restante:
            self.contrato.saldo_transportado = (
                self.contrato.saldo_transportado + restante
            )
            self.contrato.save(update_fields=["saldo_transportado", "atualizado_em"])

    def estornar(self) -> Decimal:
        """Desfaz a baixa: tira ``valor_pago`` da parcela e recalcula o status.

        Devolve o ``restante`` que esta baixa havia transportado para as
        parcelas seguintes (0 se não transportou) — a view usa isso para avisar
        que o saldo transportado precisa de conferência manual. Não desfaz o
        transporte automaticamente (parcelas seguintes podem já ter recebido
        baixa).
        """
        venc = self.vencimento
        restante_transportado = Decimal("0.00")
        if venc is not None:
            restante_transportado = venc.valor_previsto - venc.valor_pago
            venc.aplicar_valor_pago(venc.valor_pago - self.valor_pago)
        self.delete()
        return restante_transportado


class Cobranca(models.Model):
    """Mensagem de cobrança preparada ou enviada para um cliente em um dia."""

    class Canal(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ENVIADO = "enviado", "Enviado"
        ENTREGUE = "entregue", "Entregue"
        LIDO = "lido", "Lido"
        ERRO = "erro", "Erro"

    contrato = models.ForeignKey(
        "contratos.Contrato",
        on_delete=models.PROTECT,
        related_name="cobrancas",
    )
    vencimento = models.ForeignKey(
        Vencimento,
        on_delete=models.PROTECT,
        related_name="cobrancas",
        null=True,
        blank=True,
    )
    data_alvo = models.DateField("data da cobrança")
    canal = models.CharField(max_length=12, choices=Canal.choices, default=Canal.WHATSAPP)
    destinatario = models.CharField(max_length=20)
    mensagem = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDENTE)
    id_externo = models.CharField("ID no provedor", max_length=160, blank=True, db_index=True)
    erro = models.TextField(blank=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    enviado_em = models.DateTimeField(null=True, blank=True)
    entregue_em = models.DateTimeField(null=True, blank=True)
    lido_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_alvo", "contrato__cliente__nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["contrato", "data_alvo", "canal"],
                name="cobranca_unica_por_contrato_dia_canal",
            )
        ]

    def __str__(self):
        return f"{self.contrato} - {self.data_alvo:%d/%m/%Y} - {self.get_status_display()}"
