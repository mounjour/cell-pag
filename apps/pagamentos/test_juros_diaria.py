"""Diárias vencidas recebem um único acréscimo, sem juros sobrepostos."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.assistente.ferramentas import consultar_contrato
from apps.clientes.situacao import situacoes_dos_clientes
from apps.contratos.models import Contrato
from apps.contratos.resumo import resumo_do_cadastro
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401
from apps.pagamentos import acordos, atraso
from apps.pagamentos.agenda import resumo_cobranca
from apps.pagamentos.models import Pagamento, Vencimento
from apps.pagamentos.pix_cora import composicao_do_pix


@pytest.mark.parametrize("dias", [0, 1, 2, 10, 100])
def test_acrescimo_unico_sem_alterar_dias_reais(dias):
    hoje = datetime.date(2026, 11, 17)
    situacao = atraso.avaliar(hoje - datetime.timedelta(days=dias), Contrato.Estrutura.DIARIA, hoje)
    assert situacao.juros == Decimal("5.00" if dias else "0.00")
    assert situacao.dias_atraso == dias
    assert situacao.alertar_bloqueio == (dias >= 8)


@pytest.mark.django_db
def test_duas_diarias_de_27_50_totalizam_65_em_todos_os_canais(cliente):
    hoje = timezone.localdate()
    ct = novo_contrato(cliente, valor_total="55.00", valor_parcela="27.50", num_parcelas=2,
                       data_inicio=hoje - datetime.timedelta(days=3))
    ct.refresh_from_db()
    vencimentos = [Vencimento.objects.create(
        contrato=ct, numero=n, data_vencimento=hoje - datetime.timedelta(days=3 - n),
        valor_previsto=Decimal("27.50"),
    ) for n in (1, 2)]
    for dia in (hoje, hoje + datetime.timedelta(days=10)):
        resumo = resumo_cobranca(ct, dia)
        assert resumo["juros"] == Decimal("10.00")
        assert resumo["total"] == Decimal("65.00")
        assert [p.total for p in resumo["parcelas"]] == [Decimal("32.50")] * 2
        assert composicao_do_pix(vencimentos[0], dia) == (Decimal("55.00"), Decimal("10.00"))
        assert situacoes_dos_clientes([cliente.pk], dia)[cliente.pk].devido == Decimal("65.00")
        assert resumo_do_cadastro(ct, 0, dia)["primeira"]["valor"] == Decimal("65.00")
    retorno = consultar_contrato(ct.pk)
    assert [p["juros_hoje"] for p in retorno["parcelas"]] == ["5.00", "5.00"]

    # Quitar a primeira diária com seus juros deixa apenas a segunda diária.
    Pagamento(contrato=ct, vencimento=vencimentos[0], valor_pago=Decimal("27.50"),
              juros_pago=Decimal("5.00"), data_pagamento=hoje, forma="dinheiro").registrar()
    assert resumo_cobranca(ct, hoje)["total"] == Decimal("32.50")
    assert resumo_cobranca(ct, hoje + datetime.timedelta(days=10))["total"] == Decimal("32.50")


@pytest.mark.django_db
def test_diaria_parcial_e_perdao_nao_acumulam_juros_novamente(cliente):
    hoje = timezone.localdate()
    ct = novo_contrato(cliente, valor_parcela="27.50", num_parcelas=1)
    venc = Vencimento.objects.create(contrato=ct, numero=1,
        data_vencimento=hoje - datetime.timedelta(days=10), valor_previsto=Decimal("27.50"),
        valor_pago=Decimal("10.00"), status=Vencimento.Status.PARCIAL, juros_abonado=Decimal("2.00"))
    for dia in (hoje, hoje + datetime.timedelta(days=10)):
        assert acordos.juros_a_cobrar(venc, dia) == Decimal("3.00")
        assert resumo_cobranca(ct, dia)["total"] == Decimal("20.50")


@pytest.mark.parametrize("estrutura", [Contrato.Estrutura.MENSAL, Contrato.Estrutura.QUINZENAL,
                                       Contrato.Estrutura.SEMANAL])
def test_demais_regimes_preservam_juros_por_dia(estrutura):
    assert atraso.juros_acumulados(10, estrutura=estrutura) == Decimal("50.00")


def test_diaria_respeita_valor_configurado():
    assert atraso.juros_acumulados(10, Decimal("3.00"), estrutura="diaria") == Decimal("3.00")
