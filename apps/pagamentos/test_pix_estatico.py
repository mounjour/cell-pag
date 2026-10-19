"""Pix estático: o código é montado aqui e a Cora não é chamada para criar nada."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import brcode, cora_api, pix_cora
from apps.pagamentos.models import CobrancaCora, Vencimento

pytestmark = pytest.mark.django_db


def test_crc_confere_com_o_exemplo_oficial_do_banco_central():
    exemplo = ("00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
               "5913Fulano de Tal6008BRASILIA62070503***6304")
    assert brcode._crc16(exemplo) == "1D3D"


def test_codigo_leva_chave_valor_nome_e_referencia():
    codigo = brcode.copia_e_cola(chave="+5588999990000", valor=Decimal("350.5"), nome="José da Silva", cidade="São Paulo",
                                 referencia="CP-57")
    assert "br.gov.bcb.pix" in codigo and "+5588999990000" in codigo and "350.50" in codigo
    assert "JOSE DA SILVA" in codigo and "SAO PAULO" in codigo and "0504CP57" in codigo
    assert codigo[-4:] == brcode._crc16(codigo[:-4])


def test_valor_e_chave_sao_obrigatorios():
    with pytest.raises(ValueError):
        brcode.copia_e_cola(chave="", valor=Decimal("10"), nome="A", cidade="B")
    with pytest.raises(ValueError):
        brcode.copia_e_cola(chave="x", valor=Decimal("0"), nome="A", cidade="B")


def test_obter_cobranca_monta_o_codigo_localmente_e_acompanha_o_juros(cliente, settings, monkeypatch):
    settings.PIX_MODO, settings.CORA_PROVIDER, settings.PIX_CHAVE = "estatico", "cora", "12345678000190"
    monkeypatch.setattr(cora_api, "criar_fatura", lambda *a, **k: pytest.fail("não pode criar fatura na Cora"))
    monkeypatch.setattr(cora_api, "cancelar_fatura", lambda *a, **k: pytest.fail("não pode cancelar nada na Cora"))
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    hoje = timezone.localdate()
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"),
                                     data_vencimento=hoje - __import__("datetime").timedelta(days=2))

    pix = pix_cora.obter_ou_criar_cobranca(venc, hoje)
    assert pix.status == CobrancaCora.Status.ABERTO and pix.cora_id is None
    assert pix.valor == Decimal("310.00") and "310.00" in pix.pix_copia_e_cola  # parcela + 2 dias de juros

    depois = pix_cora.obter_ou_criar_cobranca(venc, hoje + __import__("datetime").timedelta(days=1))
    assert depois.pk == pix.pk and depois.valor == Decimal("315.00") and "315.00" in depois.pix_copia_e_cola
    assert CobrancaCora.objects.count() == 1  # o mesmo registro, sem cancelar nem recriar fatura


def test_sem_chave_pix_o_erro_aparece_em_vez_de_cobrar_sem_codigo(cliente, settings):
    settings.PIX_MODO, settings.PIX_CHAVE = "estatico", ""
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"), data_vencimento=timezone.localdate())
    pix = pix_cora.obter_ou_criar_cobranca(venc)
    assert pix.status == CobrancaCora.Status.ERRO and "chave Pix" in pix.erro and not pix.pix_copia_e_cola


def test_editar_parcela_remonta_o_pix_estatico_na_hora(cliente, settings, monkeypatch):
    from apps.pagamentos import acordos

    settings.PIX_MODO, settings.CORA_PROVIDER, settings.PIX_CHAVE = "estatico", "cora", "12345678000190"
    monkeypatch.setattr(cora_api, "cancelar_fatura", lambda *a, **k: pytest.fail("não pode cancelar nada na Cora"))
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"),
                                     data_vencimento=timezone.localdate() + __import__("datetime").timedelta(days=5))
    pix = pix_cora.obter_ou_criar_cobranca(venc)
    assert "300.00" in pix.pix_copia_e_cola

    venc.valor_previsto = Decimal("450.00")
    venc.save()
    assert acordos._renovar_pix(venc) == []

    pix.refresh_from_db()
    assert pix.valor == Decimal("450.00") and "450.00" in pix.pix_copia_e_cola and pix.cora_id is None
