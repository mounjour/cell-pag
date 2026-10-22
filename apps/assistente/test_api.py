"""Conector do Claude Desktop: chave por pessoa, ferramentas e o registro de tudo o que foi gravado."""

import datetime
import json
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.assistente.models import AcessoApi, OperacaoApi
from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos.models import Pagamento, Vencimento

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def chave(operador):
    return AcessoApi.criar(operador, "Notebook")[1]


@pytest.fixture
def parcela(cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="157.50", num_parcelas=3,
                       juros_diario=Decimal("5.00"))
    return Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("157.50"),
                                     data_vencimento=timezone.localdate() - datetime.timedelta(days=1))


def _chamar(client, chave, ferramenta, **parametros):
    return client.post(reverse("assistente:api_executar"), json.dumps({"ferramenta": ferramenta, "parametros": parametros}),
                       content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {chave}")


def test_sem_chave_ou_com_chave_ruim_nao_entra(client, operador, chave):
    assert client.get(reverse("assistente:api_ferramentas")).status_code == 401
    assert client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION="Bearer cp_errada").status_code == 401
    AcessoApi.objects.get().revogar()
    assert client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}").status_code == 401


def test_a_chave_nao_fica_guardada_em_texto(operador, chave):
    acesso = AcessoApi.objects.get()
    assert chave not in acesso.chave_hash and acesso.final_da_chave == chave[-4:] and len(acesso.chave_hash) == 64


def test_ferramentas_publicadas_com_resumo_nas_que_gravam(client, chave):
    dados = client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}").json()
    por_nome = {f["name"]: f for f in dados["ferramentas"]}
    assert {"buscar_cliente", "consultar_contrato", "listar_atrasos", "registrar_pagamento"} <= set(por_nome)
    assert por_nome["registrar_pagamento"]["grava"] is True and "resumo" in por_nome["registrar_pagamento"]["input_schema"]["required"]
    assert por_nome["buscar_cliente"]["grava"] is False and "resumo" not in por_nome["buscar_cliente"]["input_schema"]["properties"]


def test_leitura_responde_e_nao_gera_registro_de_operacao(client, chave, cliente, parcela):
    resposta = _chamar(client, chave, "buscar_cliente", texto=cliente.nome[:4])
    assert resposta.status_code == 200 and cliente.nome in resposta.json()["resultado"]
    assert OperacaoApi.objects.count() == 0


def test_gravar_pagamento_pede_resumo_e_registra_quem_fez(client, chave, operador, parcela):
    ct = parcela.contrato
    sem_resumo = _chamar(client, chave, "registrar_pagamento", contrato_id=ct.pk, valor_pago="157.50", juros_pago="5.00", forma="pix")
    assert sem_resumo.status_code == 400 and Pagamento.objects.count() == 0

    ok = _chamar(client, chave, "registrar_pagamento", contrato_id=ct.pk, valor_pago="157.50", juros_pago="5.00", forma="pix",
                 resumo="Roberto Lucas, parcela 1, R$ 157,50 + R$ 5,00 de juros, Pix")
    assert ok.status_code == 200 and ok.json()["gravou"] is True
    pagamento = Pagamento.objects.get()
    assert pagamento.valor_pago == Decimal("157.50") and pagamento.juros_pago == Decimal("5.00") and pagamento.usuario_baixa == operador
    assert "assistente" in pagamento.observacao.lower()
    parcela.refresh_from_db()
    assert parcela.status == "pago"
    assert OperacaoApi.objects.filter(ok=False).count() == 1  # a tentativa sem resumo também fica registrada
    operacao = OperacaoApi.objects.get(ok=True)
    assert operacao.grava and operacao.ok and operacao.usuario == operador and "Roberto" in operacao.parametros["resumo"]


def test_parcela_ja_paga_e_recusada_e_o_erro_fica_registrado(client, chave, parcela):
    Pagamento(contrato=parcela.contrato, vencimento=parcela, data_pagamento=timezone.localdate(), valor_pago=Decimal("157.50"), forma="pix").registrar()
    resposta = _chamar(client, chave, "registrar_pagamento", contrato_id=parcela.contrato.pk, parcela_numero=1, valor_pago="157.50", resumo="de novo")
    assert resposta.status_code == 400 and "já recebeu pagamento" in resposta.json()["erro"]
    assert Pagamento.objects.count() == 1 and OperacaoApi.objects.get().ok is False


def test_ferramenta_desconhecida_e_pedido_invalido(client, chave):
    assert _chamar(client, chave, "apagar_tudo").status_code == 400
    ruim = client.post(reverse("assistente:api_executar"), "isto nao e json", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {chave}")
    assert ruim.status_code == 400


def test_tela_cria_a_chave_e_mostra_so_uma_vez(auth_client, operador):
    resposta = auth_client.post(reverse("assistente:desktop"), {"nome": "Notebook da Yslane"})
    html = resposta.content.decode()
    chave = AcessoApi.objects.get().final_da_chave
    assert "cp_" in html and "CELULARES_CHAVE" in html and resposta["Cache-Control"] == "no-store"
    depois = auth_client.get(reverse("assistente:desktop")).content.decode()
    assert "CELULARES_CHAVE" not in depois and f"…{chave}" in depois


def test_revogar_so_a_propria_chave(auth_client, operador, django_user_model):
    outro = django_user_model.objects.create_user("outro")
    alheia = AcessoApi.criar(outro, "dele")[0]
    propria = AcessoApi.criar(operador, "minha")[0]
    assert auth_client.post(reverse("assistente:revogar", args=[alheia.pk])).status_code == 404
    assert auth_client.post(reverse("assistente:revogar", args=[propria.pk])).status_code == 302
    propria.refresh_from_db()
    assert not propria.ativo


def test_baixar_o_conector(auth_client):
    resposta = auth_client.get(reverse("assistente:conector"))
    assert resposta.status_code == 200 and b"CELULARES_CHAVE" in resposta.content
