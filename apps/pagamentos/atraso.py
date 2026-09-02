"""Cálculo de atraso, juros e status de cobrança (Fase 4).

Regras fixadas (PLANO-DO-PROJETO.md, seções 4.6 e 10):

* Juros: **R$ 5,00 fixos por dia de atraso** (valor/dia × dias de atraso).
* **7 dias de atraso → alerta de bloqueio** do aparelho. O sistema só sinaliza;
  o bloqueio em si é ação manual do vendedor.
* No atraso, a cobrança continua todos os dias.
* Status visual: verde = em dia · vermelho = atrasado/inadimplente · cinza = quitado.
  Os 4 status internos de ``Contrato.Status`` continuam existindo.
* **Semanal:** sem dia fixo. A parcela da semana só conta como atraso depois que a
  semana fecha (domingo); o atraso — e os juros — começam na segunda-feira seguinte.

Este módulo é **lógica pura**: recebe datas e a estrutura, devolve números e status.
Não gera ``Vencimento`` nem calcula valor de parcela (isso é Fase 2 e depende de
regras ainda em aberto com o Alisson).

``LIMITE_INADIMPLENTE`` (fronteira entre "atrasado" e "inadimplente") está fixado
no mesmo gatilho do bloqueio — 7 dias. Isso é uma inferência: o formulário só
definiu o gatilho dos 7 dias, não a fronteira dos status. Confirmar com o Alisson
se a inadimplência deve começar em outro ponto.
"""

import datetime
from decimal import Decimal
from typing import NamedTuple

from django.utils import timezone

from apps.contratos.models import Contrato

__all__ = [
    "VALOR_JUROS_DIA",
    "DIAS_PARA_BLOQUEIO",
    "LIMITE_INADIMPLENTE",
    "SituacaoAtraso",
    "data_efetiva_vencimento",
    "dias_de_atraso",
    "juros_acumulados",
    "classificar_status",
    "cor_do_status",
    "precisa_alertar_bloqueio",
    "avaliar",
]

#: Juros fixos por dia de atraso, em reais.
VALOR_JUROS_DIA = Decimal("5.00")

#: Dias de atraso a partir dos quais o sistema alerta para bloquear o aparelho.
DIAS_PARA_BLOQUEIO = 7

#: Dias de atraso a partir dos quais o contrato é considerado inadimplente
#: (ver observação no docstring do módulo — a confirmar com o Alisson).
LIMITE_INADIMPLENTE = 7

_CENTAVOS = Decimal("0.01")


class SituacaoAtraso(NamedTuple):
    """Retrato da cobrança de uma parcela num determinado dia."""

    dias_atraso: int
    juros: Decimal
    status: str
    cor: str
    alertar_bloqueio: bool


def _fim_da_semana(dia: datetime.date) -> datetime.date:
    """Domingo que fecha a semana (segunda→domingo) de ``dia``.

    ``date.weekday()``: segunda = 0 ... domingo = 6. O deslocamento é sempre
    dentro da mesma semana, então a soma de dias é exata.
    """
    return dia + datetime.timedelta(days=6 - dia.weekday())


def data_efetiva_vencimento(
    data_vencimento: datetime.date, estrutura: str
) -> datetime.date:
    """Data a partir da qual a parcela pode ser cobrada como atrasada.

    Igual à ``data_vencimento`` em todas as estruturas, exceto na **semanal**,
    em que vale o domingo que fecha a semana do vencimento.
    """
    if estrutura == Contrato.Estrutura.SEMANAL:
        return _fim_da_semana(data_vencimento)
    return data_vencimento


def dias_de_atraso(
    data_vencimento: datetime.date, hoje: datetime.date, estrutura: str
) -> int:
    """Dias de atraso da parcela em ``hoje`` (0 se ainda não venceu).

    Vencer "hoje" ainda não é atraso — o atraso começa no dia seguinte. Na
    semanal, começa na segunda-feira após o domingo que fecha a semana.
    """
    referencia = data_efetiva_vencimento(data_vencimento, estrutura)
    return max(0, (hoje - referencia).days)


def juros_acumulados(dias_atraso: int) -> Decimal:
    """Juros totais para ``dias_atraso`` dias (R$ 5,00 por dia)."""
    if dias_atraso < 0:
        raise ValueError("dias_atraso não pode ser negativo")
    return (VALOR_JUROS_DIA * dias_atraso).quantize(_CENTAVOS)


def classificar_status(dias_atraso: int, *, quitado: bool = False) -> str:
    """Um dos valores de ``Contrato.Status`` a partir dos dias de atraso."""
    if quitado:
        return Contrato.Status.QUITADO
    if dias_atraso <= 0:
        return Contrato.Status.EM_DIA
    if dias_atraso < LIMITE_INADIMPLENTE:
        return Contrato.Status.ATRASADO
    return Contrato.Status.INADIMPLENTE


def cor_do_status(status: str) -> str:
    """Cor da UI para o status: 'verde', 'vermelho' ou 'cinza'."""
    if status == Contrato.Status.QUITADO:
        return "cinza"
    if status == Contrato.Status.EM_DIA:
        return "verde"
    return "vermelho"


def precisa_alertar_bloqueio(dias_atraso: int) -> bool:
    """True quando o atraso atinge o gatilho de bloqueio do aparelho (7 dias)."""
    return dias_atraso >= DIAS_PARA_BLOQUEIO


def avaliar(
    data_vencimento: datetime.date,
    estrutura: str,
    hoje: datetime.date | None = None,
    *,
    quitado: bool = False,
) -> SituacaoAtraso:
    """Situação completa da parcela: dias de atraso, juros, status, cor e alerta."""
    if hoje is None:
        hoje = timezone.localdate()
    if quitado:
        return SituacaoAtraso(
            dias_atraso=0,
            juros=Decimal("0.00"),
            status=Contrato.Status.QUITADO,
            cor="cinza",
            alertar_bloqueio=False,
        )
    dias = dias_de_atraso(data_vencimento, hoje, estrutura)
    status = classificar_status(dias)
    return SituacaoAtraso(
        dias_atraso=dias,
        juros=juros_acumulados(dias),
        status=status,
        cor=cor_do_status(status),
        alertar_bloqueio=precisa_alertar_bloqueio(dias),
    )
