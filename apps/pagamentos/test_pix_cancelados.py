from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import cora_api, pix_cora
from apps.pagamentos.models import CobrancaCora, PixCancelado, Vencimento

pytestmark = pytest.mark.django_db


def test_cancelar_pix_deixa_registro_visivel_no_contrato(auth_client, cliente, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"), data_vencimento=timezone.localdate())
    pix = CobrancaCora.objects.create(vencimento=venc, valor=Decimal("440.00"), data_vencimento=venc.data_vencimento,
                                      cora_id="inv_x", status=CobrancaCora.Status.ABERTO)
    chamadas = []

    def sincroniza(cobranca, **_):
        chamadas.append(1)
        if len(chamadas) > 1:  # depois do DELETE a Cora informa que a fatura está cancelada
            cobranca.status = CobrancaCora.Status.CANCELADO
        return cobranca

    monkeypatch.setattr(pix_cora, "sincronizar_cobranca", sincroniza)
    monkeypatch.setattr(cora_api, "cancelar_fatura", lambda _id: {})

    pix_cora.cancelar_cobranca(pix, motivo="Parcela editada")
    registro = PixCancelado.objects.get()
    assert registro.contrato == ct and registro.valor == Decimal("440.00") and registro.motivo == "Parcela editada"

    html = auth_client.get(reverse("contratos:detalhe", args=[ct.pk])).content.decode()
    assert "Pix cancelados" in html and "Parcela editada" in html and "R$ 0,30" in html


def test_pix_sem_fatura_na_cora_nao_gera_registro(cliente, settings):
    settings.CORA_PROVIDER = "cora"
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"), data_vencimento=timezone.localdate())
    pix = CobrancaCora.objects.create(vencimento=venc, valor=Decimal("300.00"), data_vencimento=venc.data_vencimento)
    pix_cora.cancelar_cobranca(pix, motivo="Teste")  # nada foi criado na Cora, então não há taxa nem registro
    assert not PixCancelado.objects.exists()
