"""Editar a entrada de um contrato já cadastrado: corrigir, criar ou remover."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.contratos.tests import cliente, dados_form, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos.models import Pagamento

pytestmark = pytest.mark.django_db


def _entrada(contrato, valor="500.00", forma=Pagamento.Forma.PIX):
    pagamento = Pagamento(
        contrato=contrato, vencimento=None, valor_pago=Decimal(valor), forma=forma,
        data_pagamento=timezone.localdate(), observacao="Entrada do contrato.",
    )
    pagamento.registrar()
    return pagamento


def _editar(auth_client, contrato, cliente, **extra):
    dados = dados_form(
        cliente, aparelho="", aparelho_modelo="iPhone 11", imei="359999053372501", **extra,
    )
    return auth_client.post(reverse("contratos:editar", args=[contrato.pk]), dados, follow=True)


def _entradas(contrato):
    return list(contrato.pagamentos.filter(vencimento__isnull=True))


def test_formulario_de_edicao_mostra_a_entrada_atual(auth_client, cliente):
    ct = novo_contrato(cliente)
    _entrada(ct, "500.00", Pagamento.Forma.PIX)
    resposta = auth_client.get(reverse("contratos:editar", args=[ct.pk]))
    form = resposta.context["form"]
    assert form.initial["entrada"] == "500,00" and form.initial["entrada_forma"] == Pagamento.Forma.PIX
    html = resposta.content.decode()
    assert 'name="entrada"' in html and 'value="500,00"' in html and "apague o valor" in html


def test_corrigir_valor_e_forma_da_entrada(auth_client, cliente):
    ct = novo_contrato(cliente)
    original = _entrada(ct, "500.00", Pagamento.Forma.PIX)
    resposta = _editar(auth_client, ct, cliente, entrada="650,00", entrada_forma="dinheiro")
    assert resposta.status_code == 200
    (entrada,) = _entradas(ct)
    assert entrada.pk == original.pk  # corrigiu o lançamento, não criou outro
    assert entrada.valor_pago == Decimal("650.00") and entrada.forma == Pagamento.Forma.DINHEIRO
    assert "Entrada corrigida para R$ 650,00" in resposta.content.decode()


def test_apagar_o_valor_remove_a_entrada(auth_client, cliente):
    ct = novo_contrato(cliente)
    _entrada(ct)
    resposta = _editar(auth_client, ct, cliente, entrada="", entrada_forma="pix")
    assert _entradas(ct) == []
    assert "Entrada removida" in resposta.content.decode()


def test_contrato_sem_entrada_pode_ganhar_uma(auth_client, cliente):
    ct = novo_contrato(cliente)
    resposta = _editar(auth_client, ct, cliente, entrada="300,00", entrada_forma="pix")
    (entrada,) = _entradas(ct)
    assert entrada.valor_pago == Decimal("300.00") and entrada.forma == Pagamento.Forma.PIX
    assert "Entrada de R$ 300,00 registrada" in resposta.content.decode()


def test_sem_mudanca_nao_mexe_na_entrada(auth_client, cliente):
    ct = novo_contrato(cliente)
    original = _entrada(ct, "500.00", Pagamento.Forma.PIX)
    resposta = _editar(auth_client, ct, cliente, entrada="500,00", entrada_forma="pix")
    html = resposta.content.decode()
    assert _entradas(ct)[0].pk == original.pk and "Entrada corrigida" not in html and "Entrada removida" not in html


def test_entrada_exige_a_forma(auth_client, cliente):
    ct = novo_contrato(cliente)
    dados = dados_form(cliente, aparelho="", aparelho_modelo="iPhone 11", imei="359999053372501",
                       entrada="100,00", entrada_forma="")
    resposta = auth_client.post(reverse("contratos:editar", args=[ct.pk]), dados)
    assert resposta.status_code == 200 and "entrada_forma" in resposta.context["form"].errors
    assert _entradas(ct) == []


def test_varias_entradas_nao_sao_editaveis_aqui(auth_client, cliente):
    ct = novo_contrato(cliente)
    _entrada(ct, "300.00")
    _entrada(ct, "200.00")
    resposta = auth_client.get(reverse("contratos:editar", args=[ct.pk]))
    assert "entrada" not in resposta.context["form"].fields
    assert "2 lançamentos de entrada" in resposta.content.decode()
    _editar(auth_client, ct, cliente)
    assert len(_entradas(ct)) == 2  # nada foi alterado


def test_cadastro_novo_continua_com_os_campos_de_entrada(auth_client):
    html = auth_client.get(reverse("contratos:novo")).content.decode()
    assert 'name="entrada"' in html and 'name="entrada_forma"' in html
