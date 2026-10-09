"""Dia de cobrança: o calendário a partir da primeira cobrança (lógica pura, sem banco)."""

from datetime import date as D

import pytest

from apps.pagamentos.recorrencia import (
    data_da_parcela,
    descrever_dia_de_cobranca,
    interpretar_dia_de_cobranca,
    primeira_cobranca_para_vencimento,
    sugerir_primeira_cobranca,
)


def _datas(estrutura, primeira, dias="", n=4):
    return [data_da_parcela(None, estrutura, i, primeira, dias) for i in range(1, n + 1)]


def test_semanal_repete_o_dia_da_semana_da_primeira_cobranca():
    assert _datas("semanal", D(2026, 10, 5), n=3) == [D(2026, 10, 5), D(2026, 10, 12), D(2026, 10, 19)]


def test_quinzenal_por_dia_da_semana_e_a_cada_14_dias():
    datas = _datas("quinzenal", D(2026, 10, 7), n=3)
    assert datas == [D(2026, 10, 7), D(2026, 10, 21), D(2026, 11, 4)]
    assert {d.weekday() for d in datas} == {2}  # sempre quarta


def test_quinzenal_em_dois_dias_do_mes():
    assert _datas("quinzenal", D(2026, 10, 5), "5,20", n=5) == [
        D(2026, 10, 5), D(2026, 10, 20), D(2026, 11, 5), D(2026, 11, 20), D(2026, 12, 5)]
    # começando no segundo dia
    assert _datas("quinzenal", D(2026, 10, 20), "5,20", n=3) == [D(2026, 10, 20), D(2026, 11, 5), D(2026, 11, 20)]


def test_mensal_mantem_o_dia_e_cai_no_ultimo_dia_do_mes_curto():
    assert _datas("mensal", D(2026, 1, 31), "31") == [D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]


def test_sem_primeira_cobranca_vale_a_regra_antiga_da_data_da_compra():
    assert data_da_parcela(D(2026, 9, 25), "semanal", 1) == D(2026, 10, 2)
    assert data_da_parcela(D(2026, 9, 25), "quinzenal", 1) == D(2026, 10, 10)  # 15 dias
    assert data_da_parcela(D(2026, 9, 25), "mensal", 2) == D(2026, 11, 25)


@pytest.mark.parametrize("estrutura, vencimento, pagas, dias", [
    ("semanal", D(2026, 10, 5), 2, ""),
    ("quinzenal", D(2026, 10, 7), 3, ""),
    ("quinzenal", D(2026, 10, 20), 5, "5,20"),
    ("quinzenal", D(2026, 10, 5), 4, "5,20"),
    ("mensal", D(2026, 10, 15), 4, "15"),
    ("mensal", D(2026, 3, 31), 1, "31"),
    ("semanal", D(2026, 10, 5), 0, ""),
])
def test_primeira_cobranca_reconstruida_para_tras_bate_com_o_vencimento(estrutura, vencimento, pagas, dias):
    primeira = primeira_cobranca_para_vencimento(vencimento, pagas, estrutura, dias)
    assert data_da_parcela(None, estrutura, pagas + 1, primeira, dias) == vencimento


def test_sugestao_parte_de_um_periodo_depois_da_compra():
    # sexta 25/09: a semanal de sexta cai 7 dias depois; a mensal do dia 25, no mês seguinte
    assert sugerir_primeira_cobranca(D(2026, 9, 25), "semanal", dia_semana=4) == D(2026, 10, 2)
    assert sugerir_primeira_cobranca(D(2026, 9, 25), "mensal", dias_do_mes=[25]) == D(2026, 10, 25)
    # compra em 22/07, dias 5 e 20: um período depois (≥ 06/08) → 20/08
    assert sugerir_primeira_cobranca(D(2026, 7, 22), "quinzenal", dias_do_mes=[5, 20]) == D(2026, 8, 20)


def test_interpretar_sugere_a_data_quando_nao_vem_primeira_cobranca():
    primeira, dias = interpretar_dia_de_cobranca("semanal", D(2026, 9, 25), dia_semana=4)
    assert (primeira, dias) == (D(2026, 10, 2), "")
    primeira, dias = interpretar_dia_de_cobranca("quinzenal", D(2026, 7, 22), quinzena="dias_mes", dia_mes=20, dia_mes_2=5)
    assert (primeira, dias) == (D(2026, 8, 20), "5,20")
    primeira, dias = interpretar_dia_de_cobranca("mensal", D(2026, 9, 25), dia_mes=25)
    assert (primeira, dias) == (D(2026, 10, 25), "25")


def test_mensal_sem_dia_usa_o_dia_da_primeira_cobranca():
    assert interpretar_dia_de_cobranca("mensal", D(2026, 9, 1), primeira_cobranca=D(2026, 11, 15)) == (D(2026, 11, 15), "15")


@pytest.mark.parametrize("kwargs, trecho", [
    ({"estrutura": "semanal"}, "dia da semana"),
    ({"estrutura": "semanal", "dia_semana": 0, "primeira_cobranca": D(2026, 10, 7)}, "quarta-feira"),
    ({"estrutura": "mensal"}, "dia do mês"),
    ({"estrutura": "mensal", "dia_mes": 40}, "entre 1 e 31"),
    ({"estrutura": "mensal", "dia_mes": 15, "primeira_cobranca": D(2026, 10, 16)}, "dia 15"),
    ({"estrutura": "quinzenal", "quinzena": "dias_mes", "dia_mes": 5}, "dois dias"),
    ({"estrutura": "quinzenal", "quinzena": "dias_mes", "dia_mes": 5, "dia_mes_2": 5}, "diferentes"),
    ({"estrutura": "quinzenal", "quinzena": "dias_mes", "dia_mes": 5, "dia_mes_2": 20, "primeira_cobranca": D(2026, 10, 6)}, "5 e 20"),
    ({"estrutura": "diaria"}, "frequência"),
])
def test_interpretar_recusa_escolhas_incoerentes_com_mensagem_clara(kwargs, trecho):
    with pytest.raises(ValueError, match=trecho):
        interpretar_dia_de_cobranca(kwargs.pop("estrutura"), D(2026, 9, 1), **kwargs)


def test_descricao_em_linguagem_simples():
    assert descrever_dia_de_cobranca("semanal", D(2026, 9, 1), D(2026, 10, 5)) == "Toda segunda-feira"
    assert descrever_dia_de_cobranca("quinzenal", D(2026, 9, 1), D(2026, 10, 7)) == "A cada 14 dias, sempre quarta-feira"
    assert descrever_dia_de_cobranca("quinzenal", D(2026, 9, 1), D(2026, 10, 5), "5,20") == "Dias 5 e 20 de cada mês"
    assert descrever_dia_de_cobranca("mensal", D(2026, 9, 1), D(2026, 10, 15), "15") == "Todo dia 15"
    assert descrever_dia_de_cobranca("quinzenal", D(2026, 9, 1)) == "A cada 15 dias, a partir da compra"
