"""Testes do cálculo de atraso, juros e status (apps.pagamentos.atraso).

Lógica pura — não tocam no banco. As datas âncora usam a semana de
2026-01-05 (segunda) a 2026-01-11 (domingo).
"""

import datetime
from decimal import Decimal

import pytest

from apps.contratos.models import Contrato
from apps.pagamentos import atraso

SEG = datetime.date(2026, 1, 5)  # segunda-feira
QUA = datetime.date(2026, 1, 7)  # quarta-feira
DOM = datetime.date(2026, 1, 11)  # domingo (fecha a semana de SEG)
SEG_SEGUINTE = datetime.date(2026, 1, 12)
QUA_SEGUINTE = datetime.date(2026, 1, 14)


def test_semana_ancora_esta_correta():
    assert SEG.weekday() == 0
    assert DOM.weekday() == 6


# ── dias_de_atraso: estruturas com data de vencimento concreta ────────────────

@pytest.mark.parametrize("estrutura", ["diaria", "dezena", "quinzenal", "mensal"])
def test_vencer_hoje_nao_e_atraso(estrutura):
    venc = datetime.date(2026, 3, 10)
    assert atraso.dias_de_atraso(venc, venc, estrutura) == 0


@pytest.mark.parametrize("estrutura", ["diaria", "dezena", "quinzenal", "mensal"])
def test_antes_do_vencimento_nao_e_atraso(estrutura):
    venc = datetime.date(2026, 3, 10)
    assert atraso.dias_de_atraso(venc, datetime.date(2026, 3, 5), estrutura) == 0


@pytest.mark.parametrize("estrutura", ["diaria", "dezena", "quinzenal", "mensal"])
def test_conta_dias_apos_o_vencimento(estrutura):
    venc = datetime.date(2026, 3, 10)
    assert atraso.dias_de_atraso(venc, datetime.date(2026, 3, 13), estrutura) == 3


# ── dias_de_atraso: semanal (janela até o fim da semana) ─────────────────────

def test_semanal_nao_atrasa_ate_o_domingo():
    # Vencimento numa quarta; até o domingo da mesma semana não há atraso.
    assert atraso.dias_de_atraso(QUA, DOM, "semanal") == 0


def test_semanal_atraso_comeca_na_segunda_seguinte():
    assert atraso.dias_de_atraso(QUA, SEG_SEGUINTE, "semanal") == 1


def test_semanal_conta_a_partir_do_fim_da_semana():
    assert atraso.dias_de_atraso(QUA, QUA_SEGUINTE, "semanal") == 3


def test_semanal_vencimento_no_proprio_domingo():
    assert atraso.dias_de_atraso(DOM, DOM, "semanal") == 0
    assert atraso.dias_de_atraso(DOM, SEG_SEGUINTE, "semanal") == 1


def test_data_efetiva_so_muda_na_semanal():
    assert atraso.data_efetiva_vencimento(QUA, "mensal") == QUA
    assert atraso.data_efetiva_vencimento(QUA, "semanal") == DOM


# ── juros ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "dias,esperado",
    [(0, "0.00"), (1, "5.00"), (4, "20.00"), (7, "35.00"), (10, "50.00")],
)
def test_juros_acumulados(dias, esperado):
    assert atraso.juros_acumulados(dias) == Decimal(esperado)


def test_juros_negativo_e_erro():
    with pytest.raises(ValueError):
        atraso.juros_acumulados(-1)


# ── classificação de status ──────────────────────────────────────────────────

def test_status_em_dia():
    assert atraso.classificar_status(0) == Contrato.Status.EM_DIA


@pytest.mark.parametrize("dias", [1, 3, 6])
def test_status_atrasado_ate_6_dias(dias):
    assert atraso.classificar_status(dias) == Contrato.Status.ATRASADO


@pytest.mark.parametrize("dias", [7, 15, 90])
def test_status_inadimplente_a_partir_de_7_dias(dias):
    assert atraso.classificar_status(dias) == Contrato.Status.INADIMPLENTE


def test_status_quitado_ignora_atraso():
    assert atraso.classificar_status(30, quitado=True) == Contrato.Status.QUITADO


@pytest.mark.parametrize(
    "status,cor",
    [
        (Contrato.Status.EM_DIA, "verde"),
        (Contrato.Status.ATRASADO, "vermelho"),
        (Contrato.Status.INADIMPLENTE, "vermelho"),
        (Contrato.Status.QUITADO, "cinza"),
    ],
)
def test_cor_do_status(status, cor):
    assert atraso.cor_do_status(status) == cor


# ── alerta de bloqueio ───────────────────────────────────────────────────────

@pytest.mark.parametrize("dias,esperado", [(0, False), (6, False), (7, True), (20, True)])
def test_precisa_alertar_bloqueio(dias, esperado):
    assert atraso.precisa_alertar_bloqueio(dias) is esperado


# ── avaliar: integração das partes ───────────────────────────────────────────

def test_avaliar_em_dia():
    venc = datetime.date(2026, 3, 10)
    s = atraso.avaliar(venc, "mensal", hoje=venc)
    assert s == atraso.SituacaoAtraso(0, Decimal("0.00"), Contrato.Status.EM_DIA, "verde", False)


def test_avaliar_atrasado_dispara_bloqueio_aos_8_dias():
    venc = datetime.date(2026, 3, 10)
    s = atraso.avaliar(venc, "mensal", hoje=datetime.date(2026, 3, 18))
    assert s.dias_atraso == 8
    assert s.juros == Decimal("40.00")
    assert s.status == Contrato.Status.INADIMPLENTE
    assert s.cor == "vermelho"
    assert s.alertar_bloqueio is True


def test_avaliar_semanal_usa_a_janela():
    s = atraso.avaliar(QUA, "semanal", hoje=SEG_SEGUINTE)
    assert s.dias_atraso == 1
    assert s.juros == Decimal("5.00")
    assert s.status == Contrato.Status.ATRASADO
    assert s.alertar_bloqueio is False


def test_avaliar_quitado():
    venc = datetime.date(2026, 1, 1)
    s = atraso.avaliar(venc, "mensal", hoje=datetime.date(2026, 6, 1), quitado=True)
    assert s.status == Contrato.Status.QUITADO
    assert s.cor == "cinza"
    assert s.juros == Decimal("0.00")
    assert s.alertar_bloqueio is False


def test_avaliar_usa_hoje_do_sistema_quando_omitido():
    venc = datetime.date(2020, 1, 1)  # bem no passado
    s = atraso.avaliar(venc, "mensal")
    assert s.dias_atraso > 0
    assert s.status == Contrato.Status.INADIMPLENTE
