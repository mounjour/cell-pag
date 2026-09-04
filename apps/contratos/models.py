"""Contrato de venda a prazo de um aparelho e seus documentos anexos.

Fase 1 (Cadastros): cadastro do contrato + anexo de documentos.

Fase 2 (Estruturas e agenda): a geração de `Vencimento` e a `data_prevista_quitacao`
já são automáticas — ver `gerar_vencimentos()` / `atualizar_data_prevista_quitacao()`
aqui e a recorrência de datas em `apps.pagamentos.recorrencia`. O job diário
`manage.py gerar_vencimentos` roda os dois em massa + `sincronizar_status()`.
`valor_parcela` e `num_parcelas` continuam **manuais** por decisão (o cálculo é
feito fora do sistema — PLANO-DO-PROJETO.md, seção 5); sem `valor_parcela` não há
como gerar vencimentos, e sem `num_parcelas` não há data de quitação.

Fase 4 (Atraso): `situacao_atraso()` mede o atraso pela parcela (`Vencimento`)
em aberto mais antiga (`parcela_em_aberto()` / `data_referencia_atraso()`) —
`proximo_vencimento` só entra como fallback manual enquanto o contrato ainda
não tem vencimentos gerados.
"""

import datetime
from decimal import Decimal

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
        help_text="Anotação livre (ex.: quinzenal — data combinada com o Alisson). Não entra no cálculo.",
    )
    proximo_vencimento = models.DateField(
        "próximo vencimento",
        null=True,
        blank=True,
        help_text=(
            "Data da próxima parcela a receber. Usada no cálculo de atraso e juros só "
            "enquanto o contrato não tem vencimentos gerados (Vencimento) — depois "
            "disso quem manda é a parcela em aberto mais antiga."
        ),
    )

    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.EM_DIA
    )
    data_prevista_quitacao = models.DateField(
        "data prevista de quitação",
        null=True,
        blank=True,
        help_text="Calculada pelo sistema (data da última parcela) quando há valor e nº de parcelas.",
    )
    saldo_transportado = models.DecimalField(
        "saldo transportado",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Saldo de um pagamento parcial (positivo = ainda devido; negativo = "
            "crédito) que não teve parcela em aberto seguinte onde cair. É "
            "somado à próxima parcela gerada por gerar_vencimentos(). Fase 3."
        ),
    )
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

    # ── Fase 2: parcela × total (aviso no cadastro) ──────────────────────────

    @property
    def total_das_parcelas(self):
        """``valor_parcela × num_parcelas`` quando ambos existem; senão ``None``."""
        if self.valor_parcela is None or not self.num_parcelas:
            return None
        return self.valor_parcela * self.num_parcelas

    @property
    def parcelas_conferem(self):
        """``True``/``False`` se ``valor_parcela × num_parcelas`` bate com
        ``valor_total``; ``None`` quando faltam dados para comparar.

        O sistema não calcula a parcela (é feita fora — seção 5 do plano), só
        confere: divergência vira um aviso, não um erro de validação.
        """
        total = self.total_das_parcelas
        if total is None:
            return None
        return total == self.valor_total

    # ── Fase 2: geração de vencimentos ──────────────────────────────────────

    #: Teto de parcelas geradas quando o contrato não informa `num_parcelas`
    #: (~1 ano de diária). Evita laço gigante; o job roda todo dia e completa.
    MAX_PARCELAS_SEM_TETO = 400

    def gerar_vencimentos(self, dias_a_frente: int = 60, hoje=None) -> list:
        """Cria os `Vencimento` que faltam, das parcelas vencidas até
        ``hoje + dias_a_frente``.

        Precisa de ``valor_parcela`` (vira ``valor_previsto``). Respeita
        ``num_parcelas`` como teto quando informado. Idempotente — usa o
        ``UniqueConstraint(contrato, numero)`` e só cria o que falta. Contrato
        quitado não gera nada. Devolve a lista de `Vencimento` criados.
        """
        from apps.pagamentos import recorrencia
        from apps.pagamentos.models import Vencimento

        if self.quitado or self.valor_parcela is None:
            return []
        if hoje is None:
            from django.utils import timezone

            hoje = timezone.localdate()
        horizonte = hoje + datetime.timedelta(days=dias_a_frente)

        ja_existem = set(self.vencimentos.values_list("numero", flat=True))
        teto = self.num_parcelas or self.MAX_PARCELAS_SEM_TETO

        novos = []
        for numero in range(1, teto + 1):
            data = recorrencia.data_da_parcela(self.data_inicio, self.estrutura, numero)
            if data > horizonte:
                break
            if numero not in ja_existem:
                novos.append(
                    Vencimento(
                        contrato=self,
                        numero=numero,
                        data_vencimento=data,
                        valor_previsto=self.valor_parcela,
                    )
                )
        # Fase 3: drena o saldo de um parcial que não achou parcela onde cair
        # (ver Pagamento.registrar). Soma na primeira parcela nova, cascateando
        # se for um crédito maior que ela.
        if novos and self.saldo_transportado:
            restante = self.saldo_transportado
            for venc in novos:
                novo_valor = venc.valor_previsto + restante
                if novo_valor < 0:
                    venc.valor_previsto = Decimal("0.00")
                    restante = novo_valor
                else:
                    venc.valor_previsto = novo_valor
                    restante = Decimal("0.00")
                    break
            self.saldo_transportado = restante
            self.save(update_fields=["saldo_transportado", "atualizado_em"])

        if novos:
            Vencimento.objects.bulk_create(novos)
        return novos

    def atualizar_data_prevista_quitacao(self, salvar: bool = True) -> bool:
        """Recalcula ``data_prevista_quitacao`` (= data da parcela nº
        ``num_parcelas``). Devolve ``True`` se o valor mudou.

        Sem ``num_parcelas`` o resultado é ``None`` (não dá para saber a data).
        """
        from apps.pagamentos import recorrencia

        nova = recorrencia.data_prevista_quitacao(
            self.data_inicio, self.estrutura, self.num_parcelas
        )
        if nova == self.data_prevista_quitacao:
            return False
        self.data_prevista_quitacao = nova
        if salvar:
            self.save(update_fields=["data_prevista_quitacao", "atualizado_em"])
        return True

    # ── Fase 4: atraso, juros e status ───────────────────────────────────────
    # A lógica pura vive em apps/pagamentos/atraso.py. Aqui só ligamos ao
    # contrato (estrutura + data de referência + se está quitado). O import é
    # feito dentro dos métodos para evitar import circular com aquele módulo.

    def parcela_em_aberto(self):
        """`Vencimento` mais antigo (menor nº) ainda não pago — a próxima
        parcela a cobrar. ``None`` quando o contrato ainda não tem vencimentos
        gerados (falta `valor_parcela`, ou o job diário ainda não rodou)."""
        from apps.pagamentos.models import Vencimento

        return (
            self.vencimentos.exclude(status=Vencimento.Status.PAGO)
            .order_by("numero")
            .first()
        )

    def data_referencia_atraso(self):
        """Data usada para medir atraso: a da `parcela_em_aberto()` quando já
        há vencimentos gerados; senão cai no `proximo_vencimento` manual."""
        parcela = self.parcela_em_aberto()
        return parcela.data_vencimento if parcela else self.proximo_vencimento

    def situacao_atraso(self, hoje=None):
        """`SituacaoAtraso` calculada a partir de `data_referencia_atraso()`.

        Devolve ``None`` quando não há data de referência — sem vencimentos
        gerados e sem `proximo_vencimento` manual não dá para medir atraso.
        """
        data_referencia = self.data_referencia_atraso()
        if data_referencia is None:
            return None
        from apps.pagamentos import atraso

        return atraso.avaliar(
            data_referencia,
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
