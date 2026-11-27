from unittest.mock import patch

import pytest
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.contratos.tests import novo_contrato

pytestmark = pytest.mark.django_db


@pytest.fixture
def contrato():
    cliente = Cliente(nome="Cliente de exclusão", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    cliente.full_clean()
    cliente.save()
    return novo_contrato(cliente)


def test_get_nao_exclui_contrato(auth_client, contrato):
    resposta = auth_client.get(reverse("contratos:excluir", args=[contrato.pk]))
    assert resposta.status_code == 405
    assert Contrato.objects.filter(pk=contrato.pk).exists()


def test_exclusao_json_redireciona_para_cliente(auth_client, contrato):
    destino = reverse("clientes:detalhe", args=[contrato.cliente_id])
    resposta = auth_client.post(
        reverse("contratos:excluir", args=[contrato.pk]), HTTP_ACCEPT="application/json"
    )
    assert resposta.status_code == 200
    assert resposta.json() == {"redirect_url": destino}
    assert not Contrato.objects.filter(pk=contrato.pk).exists()


@pytest.mark.parametrize("json", [True, False])
def test_falha_exclusao_preserva_contrato(auth_client, contrato, json):
    with patch("apps.contratos.views.excluir_contrato", side_effect=RuntimeError("falha interna")):
        resposta = auth_client.post(
            reverse("contratos:excluir", args=[contrato.pk]),
            HTTP_ACCEPT="application/json" if json else "text/html",
        )
    assert Contrato.objects.filter(pk=contrato.pk).exists()
    if json:
        assert resposta.status_code == 500
        assert "erro" in resposta.json()
        assert "falha interna" not in resposta.content.decode()
    else:
        assert resposta.status_code == 302
        assert resposta.url == reverse("contratos:detalhe", args=[contrato.pk])


def test_exclusao_exige_login(client, contrato):
    resposta = client.post(reverse("contratos:excluir", args=[contrato.pk]))
    assert resposta.status_code == 302
    assert Contrato.objects.filter(pk=contrato.pk).exists()
