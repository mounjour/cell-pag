"""Editar parcela: data, valor e valor a mais — e o contrato editável levando isso às parcelas."""

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import parcelas
from apps.pagamentos.agenda import parcelas_a_cobrar
from apps.pagamentos.models import Vencimento

pytestmark = pytest.mark.django_db


def HOJE():
    return timezone.localdate()


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def parcela(cliente):
    ct = novo_contrato(
        cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3,
        juros_diario=Decimal("5.00"),
    )
    v1 = Vencimento.objects.create(
        contrato=ct, numero=1, data_vencimento=HOJE() - datetime.timedelta(days=10), valor_previsto=Decimal("300.00"))
    Vencimento.objects.create(
        contrato=ct, numero=2, data_vencimento=HOJE() + datetime.timedelta(days=20), valor_previsto=Decimal("300.00"))
    return v1


def _recarrega(v):
    return Vencimento.objects.get(pk=v.pk)


def test_valor_a_mais_entra_na_cobranca(parcela):
    parcelas.editar_parcela(
        parcela, data_vencimento=parcela.data_vencimento, valor_base=Decimal("300.00"),
        acrescimo=Decimal("80.00"), motivo="capinha",
    )
    parcela = _recarrega(parcela)
    assert parcela.valor_previsto == Decimal("380.00")
    assert parcela.acrescimo == Decimal("80.00") and parcela.acrescimo_motivo == "capinha"
    cobrada = parcelas_a_cobrar(parcela.contrato, HOJE())[0]
    assert cobrada.total == Decimal("430.00")  # 380 da parcela + 50 de juros (10 dias)








def test_tela_de_edicao_da_parcela(auth_client, parcela):
    url = reverse("pagamentos:parcela_editar", args=[parcela.pk])
    assert auth_client.get(url).status_code == 200
    resp = auth_client.post(url, {
        "data_vencimento": parcela.data_vencimento.isoformat(), "valor_base": "300,00",
        "acrescimo": "25,50", "motivo": "película",
    })
    assert resp.status_code == 302
    assert _recarrega(parcela).valor_previsto == Decimal("325.50")


def test_recalculo_do_contrato_mantem_o_valor_a_mais(parcela):
    parcelas.editar_parcela(
        parcela, data_vencimento=parcela.data_vencimento, valor_base=Decimal("300.00"), acrescimo=Decimal("80.00"),
    )
    contrato = parcela.contrato
    contrato.valor_parcela = Decimal("350.00")
    contrato.save()
    mudadas = parcelas.ressincronizar_parcelas_em_aberto(contrato)
    assert mudadas == 2
    assert _recarrega(parcela).valor_previsto == Decimal("430.00")  # 350 + 80 a mais
    assert Vencimento.objects.get(contrato=contrato, numero=2).valor_previsto == Decimal("350.00")


def test_editar_contrato_marca_parcelas_ja_pagas(auth_client, cliente):
    """O caso do contrato do dia 15: parcelas de agosto e setembro pagas fora do sistema."""
    ct = novo_contrato(
        cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=6,
        data_inicio=datetime.date(2026, 6, 28), primeira_cobranca=datetime.date(2026, 8, 15),
        dias_cobranca_mes="15", imei="356938035643809",
    )
    resp = auth_client.post(reverse("contratos:editar", args=[ct.pk]), {
        "cliente": cliente.pk, "apelido": ct.apelido, "aparelho_modelo": ct.aparelho_modelo, "imei": ct.imei,
        "valor_total": "1800,00", "num_parcelas": "6", "estrutura": "mensal", "data_inicio": "2026-06-28",
        "primeira_cobranca": "2026-08-15", "dia_mes": "15", "status": ct.status, "parcelas_ja_pagas": "2",
    })
    assert resp.status_code == 302, getattr(resp, "context", None) and resp.context["form"].errors
    pagas = list(ct.vencimentos.filter(status=Vencimento.Status.PAGO).values_list("numero", flat=True))
    assert pagas == [1, 2]
