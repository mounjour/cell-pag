"""Resumo da cobrança mostrado ao conferir o contrato (lógica pura, sem banco)."""

import datetime
from decimal import Decimal

from apps.contratos.models import Contrato
from apps.contratos.resumo import resumo_do_cadastro

D = datetime.date


def contrato(estrutura=Contrato.Estrutura.MENSAL, inicio=D(2026, 9, 1), total="1200.00", n=12):
    c = Contrato(valor_total=Decimal(total), num_parcelas=n, estrutura=estrutura, data_inicio=inicio)
    c.valor_parcela = Contrato.valor_da_parcela(total, n)
    c.juros_diario = Decimal("5.00")
    return c


def test_contrato_novo_primeira_cobranca_no_primeiro_vencimento():
    r = resumo_do_cadastro(contrato(), 0, hoje=D(2026, 10, 6))
    assert r["primeira"]["quando"] == "proxima_rotina"  # 01/10 já venceu → atrasada
    r = resumo_do_cadastro(contrato(inicio=D(2026, 10, 6)), 0, hoje=D(2026, 10, 6))
    assert r["primeira"] == {
        "quando": "no_vencimento", "data": D(2026, 11, 6), "numero": 1,
        "valor": Decimal("100.00"), "parcelas": 1, "com_atraso": False, "juros": Decimal("0.00"),
    }
    assert (r["total"], r["pagas"], r["restantes"], r["atrasadas"], r["a_vencer"]) == (12, 0, 12, 0, 12)
    assert r["debito_em_atraso"] == Decimal("0.00") and r["saldo_restante"] == Decimal("1200.00")
    assert r["status_esperado"] == "em_dia" and r["alerta_bloqueio"] is False


def test_contrato_em_andamento_com_atraso_e_juros():
    # mensal, início 01/07: vencimentos 01/08, 01/09, 01/10, 01/11... Hoje 06/10.
    r = resumo_do_cadastro(contrato(inicio=D(2026, 7, 1)), 1, hoje=D(2026, 10, 6))
    assert r["pagas"] == 1 and r["restantes"] == 11
    assert r["atrasadas"] == 2  # parcelas 2 (01/09) e 3 (01/10)
    assert r["maior_atraso_dias"] == 35  # 01/09 → 06/10
    assert r["juros_atrasado"] == Decimal("5.00") * (35 + 5)
    assert r["debito_em_atraso"] == Decimal("200.00") + Decimal("200.00")
    assert r["primeira"]["quando"] == "proxima_rotina"
    assert r["primeira"]["valor"] == Decimal("400.00") and r["primeira"]["parcelas"] == 2
    assert r["status_esperado"] == "inadimplente" and r["alerta_bloqueio"] is True
    assert r["saldo_restante"] == Decimal("1100.00") and r["ja_pago_em_parcelas"] == Decimal("100.00")


def test_vence_hoje_nao_conta_como_atraso():
    r = resumo_do_cadastro(contrato(inicio=D(2026, 9, 6)), 0, hoje=D(2026, 10, 6))
    assert r["atrasadas"] == 0 and r["vencem_hoje"] == 1
    assert r["primeira"]["quando"] == "proxima_rotina" and r["primeira"]["valor"] == Decimal("100.00")


def test_tudo_pago_nao_tem_cobranca():
    r = resumo_do_cadastro(contrato(), 12, hoje=D(2026, 10, 6))
    assert r["primeira"] is None and r["restantes"] == 0 and r["saldo_restante"] == Decimal("0.00")


def test_sem_numero_de_parcelas_nao_ha_resumo():
    c = contrato()
    c.num_parcelas = None
    assert resumo_do_cadastro(c, 0, hoje=D(2026, 10, 6)) is None
