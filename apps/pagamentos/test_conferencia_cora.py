"""Conferência com a Cora: o extrato contra o que o sistema registrou (só leitura)."""

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import cora_api
from apps.pagamentos.models import Pagamento, RecebimentoCora, Vencimento

pytestmark = pytest.mark.django_db


def _mov(identificador, sentido, valor, tipo, nome=""):
    return {"id": identificador, "sentido": sentido, "valor": Decimal(valor), "quando": timezone.now(), "tipo": tipo, "nome": nome}


@pytest.fixture(autouse=True)
def _ambiente(settings):
    cache.clear()
    settings.CORA_PROVIDER = "cora"
    yield
    cache.clear()


def test_mostra_entrada_nao_registrada_taxa_e_baixa_sem_credito(auth_client, cliente, monkeypatch):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"), data_vencimento=timezone.localdate())
    Pagamento(contrato=ct, vencimento=venc, data_pagamento=timezone.localdate(), valor_pago=Decimal("300.00"),
              forma=Pagamento.Forma.PIX).registrar()  # Pix lançado à mão, sem crédito no extrato
    RecebimentoCora.objects.create(entrada_id="e1", valor=Decimal("55.00"), recebido_em=timezone.now(), tipo="PIX", nome="Fulano de Tal")
    movimentos = [
        _mov("e1", "CREDIT", "55.00", "PIX", "Fulano de Tal"),
        _mov("f1", "DEBIT", "0.30", "FEE"),
        _mov("s1", "DEBIT", "44.90", "SUBSCRIPTION"),
    ]
    monkeypatch.setattr(cora_api, "listar_movimentos", lambda inicio, fim: movimentos)

    html = auth_client.get(reverse("pagamentos:conferencia_cora")).content.decode()
    assert "Fulano de Tal" in html and "R$ 55.00" in html or "R$ 55,00" in html
    assert "sem crédito no extrato" in html and cliente.nome in html
    assert "1 de R$ 0,30" in html and "pede" in html


def test_sem_diferencas_mostra_tudo_certo(auth_client, monkeypatch):
    monkeypatch.setattr(cora_api, "listar_movimentos", lambda inicio, fim: [])
    html = auth_client.get(reverse("pagamentos:conferencia_cora")).content.decode()
    assert "Tudo certo" in html


def test_cora_fora_do_ar_avisa_sem_quebrar(auth_client, monkeypatch):
    def falha(*a, **k):
        raise cora_api.CoraErro("sem rede")

    monkeypatch.setattr(cora_api, "listar_movimentos", falha)
    resposta = auth_client.get(reverse("pagamentos:conferencia_cora"))
    assert resposta.status_code == 200 and "Não consegui consultar o extrato" in resposta.content.decode()
