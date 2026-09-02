"""Contrato de venda a prazo de um aparelho e seus documentos anexos.

ESCOPO DESTA FASE (Fase 1 — Cadastros): apenas o cadastro do contrato e o anexo
de documentos. A geração de `Vencimento` e o cálculo da parcela / data de
quitação são da Fase 2 e dependem de regras ainda em aberto
(PLANO-DO-PROJETO.md, seção 10): cálculo da parcela (R10) e regra de vencimento
de "por dezena" e "mensal" (R9). Por isso `valor_parcela`, `num_parcelas` e
`data_prevista_quitacao` são, por ora, preenchidos à mão e podem ficar em branco.
"""

from django.conf import settings
from django.db import models


class Contrato(models.Model):
    class Estrutura(models.TextChoices):
        DIARIA = "diaria", "Diária"
        SEMANAL = "semanal", "Semanal"
        DEZENA = "dezena", "Por dezena"
        QUINZENAL = "quinzenal", "Quinzenal"
        MENSAL = "mensal", "Mensal"

    class Status(models.TextChoices):
        EM_DIA = "em_dia", "Em dia"
        ATRASADO = "atrasado", "Atrasado"
        INADIMPLENTE = "inadimplente", "Inadimplente"
        QUITADO = "quitado", "Quitado"

    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.PROTECT,
        related_name="contratos",
        verbose_name="cliente",
    )
    apelido = models.CharField(
        "apelido / descrição",
        max_length=80,
        help_text='Diferencia contratos do mesmo cliente. Ex.: "iPhone 11".',
    )
    aparelho_modelo = models.CharField("aparelho (modelo)", max_length=120)
    imei = models.CharField("IMEI", max_length=20, blank=True)

    valor_total = models.DecimalField("valor total do contrato", max_digits=10, decimal_places=2)
    estrutura = models.CharField("estrutura de pagamento", max_length=12, choices=Estrutura.choices)
    valor_parcela = models.DecimalField(
        "valor da parcela", max_digits=10, decimal_places=2, null=True, blank=True
    )
    num_parcelas = models.PositiveIntegerField("nº de parcelas", null=True, blank=True)
    data_inicio = models.DateField("data de início")
    dia_referencia = models.CharField(
        "dia(s) de referência",
        max_length=40,
        blank=True,
        help_text="Ex.: quinzenal — data acordada com o Alisson.",
    )
    proximo_vencimento = models.DateField(
        "próximo vencimento",
        null=True,
        blank=True,
        help_text=(
            "Data da próxima parcela a receber. Manual por enquanto; a Fase 2 vai "
            "gerar os vencimentos automaticamente. É a base do cálculo de atraso."
        ),
    )

    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.EM_DIA
    )
    data_prevista_quitacao = models.DateField("data prevista de quitação", null=True, blank=True)
    observacoes = models.TextField("observações", blank=True)

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "contrato"
        verbose_name_plural = "contratos"
        ordering = ["cliente__nome", "apelido"]

    def __str__(self) -> str:
        return f"{self.cliente.nome} — {self.apelido}"

    @property
    def quitado(self) -> bool:
        return self.status == self.Status.QUITADO

    # ── Fase 4: atraso, juros e status ───────────────────────────────────────
    # A lógica pura vive em apps/pagamentos/atraso.py. Aqui só ligamos ao
    # contrato (estrutura + próximo vencimento + se está quitado). O import é
    # feito dentro dos métodos para evitar import circular com aquele módulo.

    def situacao_atraso(self, hoje=None):
        """`SituacaoAtraso` calculada a partir de `proximo_vencimento`.

        Devolve ``None`` quando não há `proximo_vencimento` informado — sem uma
        data de referência não dá para medir atraso.
        """
        if self.proximo_vencimento is None:
            return None
        from apps.pagamentos import atraso

        return atraso.avaliar(
            self.proximo_vencimento,
            self.estrutura,
            hoje=hoje,
            quitado=self.quitado,
        )

    @property
    def status_efetivo(self) -> str:
        """Status calculado hoje; cai no status salvo se não houver `proximo_vencimento`."""
        situacao = self.situacao_atraso()
        return situacao.status if situacao else self.status

    @property
    def status_efetivo_label(self) -> str:
        return self.Status(self.status_efetivo).label

    def sincronizar_status(self, hoje=None) -> bool:
        """Grava em `status` o status calculado. Devolve True se algo mudou.

        Não é chamado automaticamente — é o gancho para o job diário da Fase 2.
        """
        situacao = self.situacao_atraso(hoje=hoje)
        if situacao is None or situacao.status == self.status:
            return False
        self.status = situacao.status
        self.save(update_fields=["status", "atualizado_em"])
        return True


def caminho_documento(instance: "DocumentoContrato", filename: str) -> str:
    return f"contratos/{instance.contrato_id}/{filename}"


class DocumentoContrato(models.Model):
    class Tipo(models.TextChoices):
        CONTRATO_ASSINADO = "contrato_assinado", "Contrato assinado"
        RG = "rg", "RG / documento de identidade"
        COMPROVANTE_RESIDENCIA = "comprovante_residencia", "Comprovante de residência"
        OUTRO = "outro", "Outro"

    contrato = models.ForeignKey(
        Contrato, on_delete=models.CASCADE, related_name="documentos", verbose_name="contrato"
    )
    tipo = models.CharField("tipo", max_length=24, choices=Tipo.choices, default=Tipo.OUTRO)
    arquivo = models.FileField("arquivo", upload_to=caminho_documento)
    descricao = models.CharField("descrição", max_length=150, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="enviado por",
    )
    enviado_em = models.DateTimeField("enviado em", auto_now_add=True)

    class Meta:
        verbose_name = "documento do contrato"
        verbose_name_plural = "documentos do contrato"
        ordering = ["-enviado_em"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.contrato}"
