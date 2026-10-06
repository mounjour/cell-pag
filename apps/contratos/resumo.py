"""Resumo da cobrança mostrado ao conferir um contrato antes de confirmar o cadastro.

Lógica pura (sem banco): a partir do contrato ainda não salvo, de quantas parcelas
já estavam pagas e da data de hoje, diz em linguagem de balcão quando sai a primeira
cobrança, de quanto, e como está a dívida (totais, pagas, faltam, atrasadas).

As regras são as do sistema: parcela atrasa no dia seguinte ao vencimento (na
semanal, só depois do domingo que fecha a semana), juros por dia de atraso do
contrato, e a rotina diária cobra o que está atrasado ou vence no dia.
"""

import datetime
from decimal import Decimal

from apps.pagamentos import atraso
from apps.pagamentos.recorrencia import data_da_parcela

ZERO = Decimal("0.00")


def resumo_do_cadastro(contrato, parcelas_ja_pagas: int, hoje: datetime.date) -> dict | None:
    """Números e a frase da primeira cobrança; ``None`` se faltar nº ou valor da parcela."""
    total = contrato.num_parcelas
    valor = contrato.valor_parcela
    if not total or not valor:
        return None
    pagas = min(parcelas_ja_pagas or 0, total)
    juros_dia = contrato.juros_diario

    atrasadas = vencem_hoje = a_vencer = max_dias = 0
    futuras = []  # vencimentos que ainda não chegaram, em ordem
    principal_atrasado = juros_atrasado = ZERO
    cobradas_na_primeira = []  # parcelas vencidas ou que vencem hoje (entram juntas)
    primeira_futura = None
    for numero in range(pagas + 1, total + 1):
        vence = data_da_parcela(contrato.data_inicio, contrato.estrutura, numero)
        dias = atraso.dias_de_atraso(vence, hoje, contrato.estrutura)
        if dias > 0:
            atrasadas += 1
            max_dias = max(max_dias, dias)
            principal_atrasado += valor
            juros_atrasado += atraso.juros_acumulados(dias, juros_dia)
            cobradas_na_primeira.append((numero, vence, dias))
        elif vence == hoje:
            vencem_hoje += 1
            cobradas_na_primeira.append((numero, vence, 0))
        elif vence < hoje:  # semanal: venceu mas a semana ainda não fechou
            vencem_hoje += 1
            cobradas_na_primeira.append((numero, vence, 0))
        else:
            a_vencer += 1
            futuras.append((numero, vence))
            if primeira_futura is None:
                primeira_futura = (numero, vence)

    restantes = total - pagas
    resultado = {
        "total": total,
        "pagas": pagas,
        "restantes": restantes,
        "atrasadas": atrasadas,
        "vencem_hoje": vencem_hoje,
        "a_vencer": a_vencer,
        "valor_parcela": valor,
        "principal_atrasado": principal_atrasado,
        "juros_atrasado": juros_atrasado,
        "debito_em_atraso": principal_atrasado + juros_atrasado,
        "saldo_restante": valor * restantes,
        "ja_pago_em_parcelas": valor * pagas,
        "juros_por_dia": juros_dia,
        "maior_atraso_dias": max_dias,
        "status_esperado": atraso.classificar_status(max_dias),
        "alerta_bloqueio": atraso.precisa_alertar_bloqueio(max_dias),
        "ultimo_vencimento": data_da_parcela(contrato.data_inicio, contrato.estrutura, total),
        # as 3 próximas depois da primeira cobrança futura (a primeira já vai na frase)
        "proximas": [vence for _, vence in futuras[1:4]] if not cobradas_na_primeira else [vence for _, vence in futuras[:3]],
        "primeira": None,
    }
    if cobradas_na_primeira:
        a_cobrar = valor * len(cobradas_na_primeira) + juros_atrasado
        resultado["primeira"] = {
            "quando": "proxima_rotina",
            "data": None,
            "valor": a_cobrar,
            "parcelas": len(cobradas_na_primeira),
            "com_atraso": atrasadas > 0,
            "juros": juros_atrasado,
        }
    elif primeira_futura:
        numero, vence = primeira_futura
        resultado["primeira"] = {
            "quando": "no_vencimento",
            "data": vence,
            "numero": numero,
            "valor": valor,
            "parcelas": 1,
            "com_atraso": False,
            "juros": ZERO,
        }
    return resultado
