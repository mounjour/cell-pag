"""Situação de cobrança de cada cliente, para a lista de Clientes.

Calcula tudo em poucas consultas (os contratos e as parcelas em aberto de uma vez),
com as mesmas regras da tela Cobrar hoje: a parcela atrasa no dia seguinte ao
vencimento (na semanal, depois do domingo que fecha a semana), os juros são por
dia de atraso de cada parcela, e parcela que já recebeu baixa não entra (o que
faltou foi transportado para a seguinte).
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from apps.contratos.models import Contrato
from apps.pagamentos import atraso
from apps.pagamentos.models import Vencimento

ZERO = Decimal("0.00")

SEM_CONTRATO = "sem_contrato"
EM_ATRASO = "atraso"
VENCE_HOJE = "hoje"
EM_DIA = "em_dia"
QUITADO = "quitado"


@dataclass
class Situacao:
    estado: str = SEM_CONTRATO
    dias_atraso: int = 0
    devido: Decimal = ZERO          # parcelas vencidas + juros
    juros: Decimal = ZERO
    proximo_vencimento: datetime.date | None = None
    proximo_valor: Decimal = ZERO
    contratos_ativos: int = 0

    @property
    def inadimplente(self) -> bool:
        return self.dias_atraso >= atraso.LIMITE_INADIMPLENTE

    @property
    def filtro(self) -> str:
        """Grupo do filtro rápido: atraso / em_dia (inclui vence hoje) / sem_contrato / quitado."""
        return EM_DIA if self.estado == VENCE_HOJE else self.estado


def situacoes_dos_clientes(cliente_ids, hoje: datetime.date | None = None) -> dict[int, Situacao]:
    hoje = hoje or timezone.localdate()
    resultado = {pk: Situacao() for pk in cliente_ids}
    if not resultado:
        return resultado

    contratos = list(Contrato.objects.filter(cliente_id__in=resultado))
    abertas: dict[int, list[Vencimento]] = {}
    ids_ativos = [c.pk for c in contratos if not c.quitado]
    for venc in (
        Vencimento.objects.filter(contrato_id__in=ids_ativos)
        .exclude(status=Vencimento.Status.PAGO)
        .exclude(pagamentos__isnull=False)
        .order_by("data_vencimento", "numero")
    ):
        abertas.setdefault(venc.contrato_id, []).append(venc)

    for contrato in contratos:
        sit = resultado[contrato.cliente_id]
        if contrato.quitado:
            if sit.estado == SEM_CONTRATO:
                sit.estado = QUITADO
            continue
        sit.contratos_ativos += 1
        if sit.estado in (SEM_CONTRATO, QUITADO):
            sit.estado = EM_DIA
        parcelas = abertas.get(contrato.pk)
        if parcelas is None:
            # Contrato sem parcelas geradas ainda: cai na data de referência do contrato.
            ref = contrato.data_referencia_atraso()
            if ref is not None:
                dias = atraso.dias_de_atraso(ref, hoje, contrato.estrutura)
                _acumula(sit, contrato, ref, contrato.valor_parcela or ZERO, dias, hoje)
            continue
        for venc in parcelas:
            dias = atraso.dias_de_atraso(venc.data_vencimento, hoje, contrato.estrutura)
            _acumula(sit, contrato, venc.data_vencimento, venc.saldo, dias, hoje)
    return resultado


def _acumula(sit: Situacao, contrato, vencimento, valor, dias, hoje) -> None:
    if dias > 0:
        juros = atraso.juros_acumulados(dias, contrato.juros_diario)
        sit.devido += valor + juros
        sit.juros += juros
        sit.dias_atraso = max(sit.dias_atraso, dias)
        sit.estado = EM_ATRASO
    else:
        if vencimento <= hoje and sit.estado != EM_ATRASO:
            sit.estado = VENCE_HOJE  # venceu hoje (ou semanal ainda dentro da semana)
        if sit.proximo_vencimento is None or vencimento < sit.proximo_vencimento:
            sit.proximo_vencimento = vencimento
            sit.proximo_valor = valor
