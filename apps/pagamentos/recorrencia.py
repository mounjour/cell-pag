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

**Dia de cobrança** (contratos novos): em vez de derivar tudo da data da compra, o
contrato guarda a ``primeira_cobranca`` (data da parcela 1) e, quando preciso, os
dias do mês (``dias_do_mes``, ex.: "15" ou "5,20"):

* **Semanal**   — toda semana no dia da semana da primeira cobrança (7 em 7 dias).
* **Quinzenal** — duas formas: *a cada 14 dias* no mesmo dia da semana, ou *dois dias
  fixos do mês* (ex.: 5 e 20).
* **Mensal**    — todo mês no dia escolhido (mês curto cai no último dia).

Contratos antigos, sem ``primeira_cobranca``, seguem a regra da ``data_inicio`` acima.

Módulo de **lógica pura**: recebe datas + estrutura e devolve datas. Não toca no
banco, não calcula valor de parcela (esse é manual — seção 5 do plano).
"""

import calendar
import datetime

from dateutil.relativedelta import relativedelta

from apps.contratos.models import Contrato

__all__ = [
    "PASSO_EM_DIAS",
    "data_da_parcela",
    "datas_das_parcelas",
    "data_prevista_quitacao",
    "DIAS_DA_SEMANA",
    "descrever_dia_de_cobranca",
    "interpretar_dia_de_cobranca",
    "primeira_cobranca_para_vencimento",
    "sugerir_primeira_cobranca",
]

DIAS_DA_SEMANA = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)

#: Passo, em dias, de cada frequência quando o contrato tem dia de cobrança
#: (quinzenal por dia da semana = 14, para cair sempre no mesmo dia).
PASSO_COM_DIA_DE_COBRANCA = {
    Contrato.Estrutura.DIARIA: 1,
    Contrato.Estrutura.SEMANAL: 7,
    Contrato.Estrutura.DEZENA: 10,
    Contrato.Estrutura.QUINZENAL: 14,
}

#: Dias corridos entre parcelas, para as estruturas de passo fixo.
#: A mensal não entra aqui — usa ``relativedelta(months=...)``.
PASSO_EM_DIAS = {
    Contrato.Estrutura.DIARIA: 1,
    Contrato.Estrutura.SEMANAL: 7,
    Contrato.Estrutura.DEZENA: 10,
    Contrato.Estrutura.QUINZENAL: 15,
}


def _dia_no_mes(ano: int, mes: int, dia: int) -> datetime.date:
    """O ``dia`` do mês; em mês mais curto cai no último dia (30 → 28/02)."""
    return datetime.date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def _somar_meses(ano: int, mes: int, quantidade: int) -> tuple[int, int]:
    indice = ano * 12 + (mes - 1) + quantidade
    return indice // 12, indice % 12 + 1


def _dias(dias_do_mes) -> list[int]:
    """``"5,20"`` (ou lista) → ``[5, 20]`` em ordem."""
    if isinstance(dias_do_mes, str):
        dias_do_mes = [d for d in dias_do_mes.replace(";", ",").split(",") if d.strip()]
    return sorted({int(d) for d in dias_do_mes})


def _ocorrencias_do_mes(ano: int, mes: int, dias: list[int]) -> list[datetime.date]:
    return sorted({_dia_no_mes(ano, mes, d) for d in dias})


def _parcela_nos_dias_do_mes(primeira, dias, numero):
    """Parcela ``numero`` de um contrato com dias fixos no mês (a 1ª é ``primeira``)."""
    contadas = 0
    ano, mes = primeira.year, primeira.month
    while True:
        for data in _ocorrencias_do_mes(ano, mes, dias):
            if data >= primeira:
                contadas += 1
                if contadas == numero:
                    return data
        ano, mes = _somar_meses(ano, mes, 1)


def data_da_parcela(
    data_inicio: datetime.date, estrutura: str, numero: int,
    primeira_cobranca: datetime.date | None = None, dias_do_mes="",
) -> datetime.date:
    """Data de vencimento da parcela ``numero`` (1, 2, 3, ...) do contrato.

    Sem ``primeira_cobranca`` vale a regra antiga (a partir da ``data_inicio``).
    Com ela, a parcela 1 é essa data e as seguintes seguem o dia de cobrança.
    """
    if numero < 1:
        raise ValueError("o número da parcela começa em 1")
    if primeira_cobranca is None:
        if estrutura == Contrato.Estrutura.MENSAL:
            return data_inicio + relativedelta(months=numero)
        try:
            passo = PASSO_EM_DIAS[estrutura]
        except KeyError as exc:
            raise ValueError(f"estrutura de pagamento desconhecida: {estrutura!r}") from exc
        return data_inicio + datetime.timedelta(days=passo * numero)

    dias = _dias(dias_do_mes) if dias_do_mes else []
    if estrutura == Contrato.Estrutura.MENSAL:
        dia = dias[0] if dias else primeira_cobranca.day
        ano, mes = _somar_meses(primeira_cobranca.year, primeira_cobranca.month, numero - 1)
        return _dia_no_mes(ano, mes, dia)
    if estrutura == Contrato.Estrutura.QUINZENAL and len(dias) >= 2:
        return _parcela_nos_dias_do_mes(primeira_cobranca, dias, numero)
    try:
        passo = PASSO_COM_DIA_DE_COBRANCA[estrutura]
    except KeyError as exc:
        raise ValueError(f"estrutura de pagamento desconhecida: {estrutura!r}") from exc
    return primeira_cobranca + datetime.timedelta(days=passo * (numero - 1))


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


def sugerir_primeira_cobranca(
    data_inicio: datetime.date, estrutura: str, *, dia_semana: int | None = None, dias_do_mes=()
) -> datetime.date:
    """Primeira data com o dia de cobrança escolhido, a partir de **um período depois da compra**.

    É só uma sugestão: no cadastro a data fica editável (ex.: primeira cobrança combinada).
    """
    dias = _dias(dias_do_mes) if dias_do_mes else []
    if estrutura == Contrato.Estrutura.MENSAL:
        marco = data_inicio + relativedelta(months=1)
    elif estrutura == Contrato.Estrutura.QUINZENAL and len(dias) >= 2:
        marco = data_inicio + datetime.timedelta(days=15)
    else:
        passo = PASSO_COM_DIA_DE_COBRANCA[estrutura]
        marco = data_inicio + datetime.timedelta(days=passo)
        if dia_semana is None:
            return marco
        return marco + datetime.timedelta(days=(dia_semana - marco.weekday()) % 7)
    if not dias:
        return marco
    ano, mes = marco.year, marco.month
    while True:
        for data in _ocorrencias_do_mes(ano, mes, dias):
            if data >= marco:
                return data
        ano, mes = _somar_meses(ano, mes, 1)


def interpretar_dia_de_cobranca(
    estrutura: str, data_inicio: datetime.date, *, primeira_cobranca=None, quinzena="semana",
    dia_semana: int | None = None, dia_mes: int | None = None, dia_mes_2: int | None = None,
):
    """Valida o dia de cobrança escolhido e devolve ``(primeira_cobranca, dias_do_mes)``.

    ``dias_do_mes`` é ``""`` (semanal e quinzenal por dia da semana), ``"15"`` (mensal) ou
    ``"5,20"`` (quinzenal com dois dias do mês). Sem ``primeira_cobranca`` ela é sugerida.
    Levanta ``ValueError`` com a mensagem pronta para o usuário.
    """
    if estrutura not in (Contrato.Estrutura.SEMANAL, Contrato.Estrutura.QUINZENAL, Contrato.Estrutura.MENSAL):
        raise ValueError("Escolha a frequência de pagamento.")

    if estrutura == Contrato.Estrutura.MENSAL or (
        estrutura == Contrato.Estrutura.QUINZENAL and quinzena == "dias_mes"
    ):
        dias = [dia_mes]
        if estrutura == Contrato.Estrutura.QUINZENAL:
            dias.append(dia_mes_2)
        elif dia_mes is None and primeira_cobranca:
            dias = [primeira_cobranca.day]
        if any(d is None for d in dias):
            raise ValueError(
                "Informe os dois dias do mês da cobrança." if estrutura == Contrato.Estrutura.QUINZENAL
                else "Informe o dia do mês da cobrança."
            )
        if any(not 1 <= d <= 31 for d in dias):
            raise ValueError("O dia do mês deve ficar entre 1 e 31.")
        if estrutura == Contrato.Estrutura.QUINZENAL and dias[0] == dias[1]:
            raise ValueError("Os dois dias da cobrança quinzenal precisam ser diferentes.")
        dias = sorted(set(dias))
        texto = ",".join(str(d) for d in dias)
        if primeira_cobranca is None:
            return sugerir_primeira_cobranca(data_inicio, estrutura, dias_do_mes=dias), texto
        if primeira_cobranca not in _ocorrencias_do_mes(primeira_cobranca.year, primeira_cobranca.month, dias):
            quais = " e ".join(str(d) for d in dias)
            raise ValueError(f"A primeira cobrança deve cair em um dos dias escolhidos (dia {quais}).")
        return primeira_cobranca, texto

    if dia_semana is not None and not 0 <= dia_semana <= 6:
        raise ValueError("Escolha um dia da semana válido.")
    if primeira_cobranca is None:
        if dia_semana is None:
            raise ValueError("Escolha o dia da semana da cobrança.")
        return sugerir_primeira_cobranca(data_inicio, estrutura, dia_semana=dia_semana), ""
    if dia_semana is not None and primeira_cobranca.weekday() != dia_semana:
        raise ValueError(
            f"A primeira cobrança cai em {DIAS_DA_SEMANA[primeira_cobranca.weekday()]}, "
            f"mas o dia de cobrança escolhido é {DIAS_DA_SEMANA[dia_semana]}."
        )
    return primeira_cobranca, ""


def primeira_cobranca_para_vencimento(
    vencimento: datetime.date, parcelas_pagas: int, estrutura: str, dias_do_mes=""
) -> datetime.date:
    """Data da parcela 1, sabendo que a parcela ``parcelas_pagas + 1`` vence em ``vencimento``.

    Serve para contratos que já estavam em andamento (planilha): a planilha traz o próximo
    vencimento e quantas parcelas já foram pagas, e o calendário é reconstruído para trás.
    """
    dias = _dias(dias_do_mes) if dias_do_mes else []
    if estrutura == Contrato.Estrutura.MENSAL:
        dia = dias[0] if dias else vencimento.day
        ano, mes = _somar_meses(vencimento.year, vencimento.month, -parcelas_pagas)
        return _dia_no_mes(ano, mes, dia)
    if estrutura == Contrato.Estrutura.QUINZENAL and len(dias) >= 2:
        atual = vencimento
        for _ in range(parcelas_pagas):
            anteriores = [d for d in _ocorrencias_do_mes(atual.year, atual.month, dias) if d < atual]
            if anteriores:
                atual = anteriores[-1]
            else:
                ano, mes = _somar_meses(atual.year, atual.month, -1)
                atual = _ocorrencias_do_mes(ano, mes, dias)[-1]
        return atual
    passo = PASSO_COM_DIA_DE_COBRANCA[estrutura]
    return vencimento - datetime.timedelta(days=passo * parcelas_pagas)


def descrever_dia_de_cobranca(
    estrutura: str, data_inicio: datetime.date, primeira_cobranca=None, dias_do_mes=""
) -> str:
    """O dia de cobrança em linguagem simples ("Toda segunda-feira", "Dias 5 e 20 de cada mês")."""
    dias = _dias(dias_do_mes) if dias_do_mes else []
    base = primeira_cobranca or data_inicio
    if estrutura == Contrato.Estrutura.SEMANAL:
        return f"Toda {DIAS_DA_SEMANA[base.weekday()]}"
    if estrutura == Contrato.Estrutura.MENSAL:
        return f"Todo dia {dias[0] if dias else base.day}"
    if estrutura == Contrato.Estrutura.QUINZENAL:
        if len(dias) >= 2:
            return f"Dias {dias[0]} e {dias[1]} de cada mês"
        if primeira_cobranca is None:
            return "A cada 15 dias, a partir da compra"
        return f"A cada 14 dias, sempre {DIAS_DA_SEMANA[base.weekday()]}"
    return ""
