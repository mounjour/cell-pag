"""Pagamento parcial: abate a parcela e o que falta continua sendo cobrado nela até quitar."""

import datetime
import importlib
from decimal import Decimal

import pytest
from django.apps import apps as registro_de_apps
from django.utils import timezone

from apps.pagamentos import limpeza
from apps.pagamentos.agenda import parcelas_a_cobrar, resumo_cobranca
from apps.pagamentos.models import CobrancaCora, Pagamento, Vencimento
from apps.pagamentos.pix_cora import sincronizar_cobranca
from apps.pagamentos.test_cobrancas import _contrato, cliente_cobranca  # noqa: F401  (cliente_cobranca é fixture)
from apps.pagamentos.test_cora import parcela_cora  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def _paga(contrato, venc, valor, **extra):
    pagamento = Pagamento(
        contrato=contrato, vencimento=venc, valor_pago=Decimal(valor), forma=Pagamento.Forma.DINHEIRO,
        data_pagamento=timezone.localdate(), **extra,
    )
    pagamento.registrar()
    return pagamento


def test_parcela_com_pagamento_parcial_segue_na_cobranca_com_o_saldo_e_o_juros_do_atraso(cliente_cobranca):
    hoje = timezone.localdate()
    contrato = _contrato(cliente_cobranca, hoje, atraso=2)  # parcela de R$ 100, vencida há 2 dias
    venc = contrato.vencimentos.get()
    _paga(contrato, venc, "40.00")

    (item,) = parcelas_a_cobrar(contrato, hoje)
    assert item.numero == 1 and item.saldo == Decimal("60.00")
    assert item.juros == Decimal("10.00")  # 2 dias × R$ 5,00: o juros segue contando desde o vencimento da parcela
    assert resumo_cobranca(contrato, hoje)["total"] == Decimal("70.00")

    _paga(contrato, venc, "60.00")
    assert parcelas_a_cobrar(contrato, hoje) == []  # quitada: sai da cobrança


def test_encerrar_cobranca_renova_o_pix_se_a_parcela_ainda_tem_saldo(cliente_cobranca, monkeypatch):
    hoje = timezone.localdate()
    contrato = _contrato(cliente_cobranca, hoje, atraso=1)
    venc = contrato.vencimentos.get()
    chamadas = []
    monkeypatch.setattr(limpeza, "_renovar_pix", lambda v, motivo, autor: chamadas.append(("renovar", motivo)) or [])
    monkeypatch.setattr(limpeza, "_cancelar_pix", lambda v: chamadas.append(("cancelar",)) or [])
    monkeypatch.setattr(limpeza, "_resolver_mensagens", lambda p, v: [])

    limpeza.encerrar_cobranca_automatica(_paga(contrato, venc, "30.00"))
    assert chamadas == [("renovar", "Pagamento parcial")]  # continua cobrando: Pix novo, com o saldo

    chamadas.clear()
    limpeza.encerrar_cobranca_automatica(_paga(contrato, venc, "70.00"))
    assert chamadas == [("cancelar",)]  # quitou: o Pix sai de vez


def test_pix_do_saldo_pago_na_cora_quita_a_parcela_sem_virar_duplicidade(parcela_cora, monkeypatch):
    contrato = parcela_cora.contrato
    _paga(contrato, parcela_cora, "40.00")  # dinheiro: parcial
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, cora_id="inv_resto", status=CobrancaCora.Status.ABERTO, valor=Decimal("60.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "PAID", "total_paid": 6000, "occurrence_date": "2026-09-04T12:00:00Z", "pix": {"emv": "PIX"}},
    )
    sincronizar_cobranca(cobranca)
    sincronizar_cobranca(cobranca)  # o aviso da Cora pode chegar de novo: não vira outra baixa
    cobranca.refresh_from_db()
    parcela_cora.refresh_from_db()
    assert not cobranca.duplicada and cobranca.status == CobrancaCora.Status.PAGO
    assert parcela_cora.status == Vencimento.Status.PAGO and parcela_cora.pagamentos.count() == 2


def test_pix_pago_em_parcela_ja_quitada_por_outro_meio_vira_duplicidade(parcela_cora, monkeypatch):
    _paga(parcela_cora.contrato, parcela_cora, "100.00")
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, cora_id="inv_dup", status=CobrancaCora.Status.ABERTO, valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "PAID", "total_paid": 10000, "occurrence_date": "2026-09-04T12:00:00Z", "pix": {"emv": "PIX"}},
    )
    sincronizar_cobranca(cobranca)
    cobranca.refresh_from_db()
    assert cobranca.duplicada and parcela_cora.pagamentos.count() == 1


def test_baixa_parcial_antiga_nao_e_cobrada_duas_vezes(cliente_cobranca):
    """A migração marca o que faltava (já somado à parcela seguinte) como repassado, para a parcela não voltar a ser cobrada."""
    hoje = timezone.localdate()
    contrato = _contrato(cliente_cobranca, hoje, atraso=2)
    antiga = contrato.vencimentos.get()
    Vencimento.objects.filter(pk=antiga.pk).update(status=Vencimento.Status.PARCIAL, valor_pago=Decimal("60.00"))
    Pagamento.objects.create(contrato=contrato, vencimento=antiga, valor_pago=Decimal("60.00"), data_pagamento=hoje - datetime.timedelta(days=1))
    assert antiga in Vencimento.objects.em_aberto()  # sem a marcação, voltaria a ser cobrada

    migracao = importlib.import_module("apps.pagamentos.migrations.0019_parcial_continua_na_parcela")
    migracao.marcar_saldo_das_baixas_parciais_antigas(registro_de_apps, None)

    antiga.refresh_from_db()
    assert antiga.saldo_repassado == Decimal("40.00") and antiga.saldo == Decimal("0.00")
    assert antiga not in Vencimento.objects.em_aberto()
    assert parcelas_a_cobrar(contrato, hoje) == []


def test_estorno_de_baixa_parcial_antiga_limpa_o_saldo_repassado(cliente_cobranca):
    hoje = timezone.localdate()
    contrato = _contrato(cliente_cobranca, hoje, atraso=1)
    venc = contrato.vencimentos.get()
    pagamento = _paga(contrato, venc, "60.00")
    Vencimento.objects.filter(pk=venc.pk).update(saldo_repassado=Decimal("40.00"))  # como ficou pela regra antiga
    venc.refresh_from_db()
    assert pagamento.estornar() == Decimal("40.00")  # avisa que o que faltou tinha ido para a seguinte
    venc.refresh_from_db()
    assert venc.saldo_repassado == Decimal("0.00") and venc.saldo == Decimal("100.00")


def test_migracao_devolve_o_que_faltou_para_a_parcela_de_origem(cliente_cobranca):
    """Pagou 60 de 100 pela regra antiga: os 40 que faltaram foram somados à parcela 2 (140)."""
    hoje = timezone.localdate()
    contrato = _contrato(cliente_cobranca, hoje, atraso=9)  # parcela 1: R$ 100, vencida há 9 dias; valor_parcela do contrato = 100
    p1 = contrato.vencimentos.get()
    Pagamento.objects.create(contrato=contrato, vencimento=p1, valor_pago=Decimal("60.00"), data_pagamento=hoje)
    Vencimento.objects.filter(pk=p1.pk).update(status=Vencimento.Status.PARCIAL, valor_pago=Decimal("60.00"), saldo_repassado=Decimal("40.00"))
    p2 = Vencimento.objects.create(contrato=contrato, numero=2, valor_previsto=Decimal("140.00"), data_vencimento=hoje + datetime.timedelta(days=20))
    p3 = Vencimento.objects.create(contrato=contrato, numero=3, valor_previsto=Decimal("130.00"), data_vencimento=hoje + datetime.timedelta(days=50))  # fora do padrão: não é tocada

    migracao = importlib.import_module("apps.pagamentos.migrations.0020_devolver_saldo_das_baixas_parciais_antigas")
    migracao.devolver_saldo_a_parcela_de_origem(registro_de_apps, None)

    p1.refresh_from_db(), p2.refresh_from_db(), p3.refresh_from_db()
    assert p1.saldo_repassado == Decimal("0.00") and p1.saldo == Decimal("40.00")
    assert p2.valor_previsto == Decimal("100.00")  # voltou a ser a parcela do contrato
    assert p3.valor_previsto == Decimal("130.00")
    (item,) = parcelas_a_cobrar(contrato, hoje)  # e a parcela 1 volta a ser cobrada, atrasada, pelo que falta
    assert item.numero == 1 and item.saldo == Decimal("40.00") and item.dias_atraso == 9


def test_migracao_nao_mexe_quando_a_seguinte_nao_bate(cliente_cobranca):
    hoje = timezone.localdate()
    contrato = _contrato(cliente_cobranca, hoje, atraso=2)
    p1 = contrato.vencimentos.get()
    Pagamento.objects.create(contrato=contrato, vencimento=p1, valor_pago=Decimal("60.00"), data_pagamento=hoje)
    Vencimento.objects.filter(pk=p1.pk).update(status=Vencimento.Status.PARCIAL, valor_pago=Decimal("60.00"), saldo_repassado=Decimal("40.00"))
    p2 = Vencimento.objects.create(contrato=contrato, numero=2, valor_previsto=Decimal("125.00"), data_vencimento=hoje + datetime.timedelta(days=20))

    migracao = importlib.import_module("apps.pagamentos.migrations.0020_devolver_saldo_das_baixas_parciais_antigas")
    migracao.devolver_saldo_a_parcela_de_origem(registro_de_apps, None)

    p1.refresh_from_db(), p2.refresh_from_db()
    assert p1.saldo_repassado == Decimal("40.00") and p2.valor_previsto == Decimal("125.00")  # deixa como estava
