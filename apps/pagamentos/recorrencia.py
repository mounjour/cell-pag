"""Recorrência de vencimentos por estrutura de pagamento (Fase 2).

Regras fechadas (PLANO-DO-PROJETO.md, seção 5; Alisson 02–03/09):

* **Diária**    — todo dia, sem folga (domingo inclusive): a parcela ``n`` vence
  em ``data_inicio + n`` dias.
* **Semanal**   — 1×/semana: a parcela ``n`` vence em ``data_inicio + 7·n`` dias.
  A *janela de atraso* (só conta como atraso depois do domingo que fecha a
  semana) fica em :func:`apps.pagamentos.atraso.data_efetiva_vencimento`.
* **Por dezena**— a cada 10 dias corridos a partir da ``data_inicio``: parcela
  ``n`` vence em ``data_inicio + 10·n`` dias ("pegou dia 3, paga dia 13").
* **Quinzenal** — a cada 15 dias corridos a partir da ``data_inicio``: parcela
  ``n`` vence em ``data_inicio + 15·n`` dias (Alisson, 03/09).
* **Mensal**    — mesmo dia do mês da ``data_inicio``, recorrente: parcela ``n``
  vence em ``data_inicio + relativedelta(months=n)``. Meses mais curtos caem no
  último dia (31/01 → 28/02).

``n`` começa em **1** — a primeira parcela vence um período *após* a
``data_inicio`` (o dia da compra não conta como vencimento).

Módulo de **lógica pura**: recebe datas + estrutura e devolve datas. Não toca no
banco, não calcula valor de parcela (esse é manual — seção 5 do plano).
"""

import datetime

from dateutil.relativedelta import relativedelta

from apps.contratos.models import Contrato

__all__ = [
    "PASSO_EM_DIAS",
    "data_da_parcela",
    "datas_das_parcelas",
    "data_prevista_quitacao",
]

#: Dias corridos entre parcelas, para as estruturas de passo fixo.
#: A mensal não entra aqui — usa ``relativedelta(months=...)``.
PASSO_EM_DIAS = {
    Contrato.Estrutura.DIARIA: 1,
    Contrato.Estrutura.SEMANAL: 7,
    Contrato.Estrutura.DEZENA: 10,
    Contrato.Estrutura.QUINZENAL: 15,
}


def data_da_parcela(
    data_inicio: datetime.date, estrutura: str, numero: int
) -> datetime.date:
    """Data de vencimento da parcela ``numero`` (1, 2, 3, ...) do contrato."""
    if numero < 1:
        raise ValueError("o número da parcela começa em 1")
    if estrutura == Contrato.Estrutura.MENSAL:
        return data_inicio + relativedelta(months=numero)
    try:
        passo = PASSO_EM_DIAS[estrutura]
    except KeyError as exc:
        raise ValueError(f"estrutura de pagamento desconhecida: {estrutura!r}") from exc
    return data_inicio + datetime.timedelta(days=passo * numero)


def datas_das_parcelas(
    data_inicio: datetime.date, estrutura: str, num_parcelas: int
) -> list[datetime.date]:
    """Lista das datas de vencimento das parcelas 1..``num_parcelas``."""
    return [
        data_da_parcela(data_inicio, estrutura, n)
        for n in range(1, num_parcelas + 1)
    ]


def data_prevista_quitacao(
    data_inicio: datetime.date, estrutura: str, num_parcelas: int | None
) -> datetime.date | None:
    """Data da última parcela (nº ``num_parcelas``).

    Devolve ``None`` quando ``num_parcelas`` não está informado — sem o total de
    parcelas não dá para saber quando o contrato quita.
    """
    if not num_parcelas or num_parcelas < 1:
        return None
    return data_da_parcela(data_inicio, estrutura, num_parcelas)
