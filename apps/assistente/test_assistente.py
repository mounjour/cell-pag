"""Assistente: o Claude propõe e só a confirmação da pessoa grava. O Claude é substituído por um roteiro fixo."""

import datetime
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.assistente import servico
from apps.assistente.models import Acao
from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos.models import Pagamento, Vencimento

pytestmark = pytest.mark.django_db


class _Bloco(SimpleNamespace):
    def to_dict(self):
        return {k: v for k, v in vars(self).items()}


def _texto(t):
    return _Bloco(type="text", text=t)


def _ferramenta(nome, **entrada):
    return _Bloco(type="tool_use", id=f"toolu_{nome}", name=nome, input=entrada)


def _resposta(*blocos, parou="end_turn"):
    return SimpleNamespace(content=list(blocos), stop_reason=parou)


class _FalsoClaude:
    """Devolve as respostas do roteiro, uma por chamada, e guarda o que foi enviado."""

    def __init__(self, roteiro):
        self.roteiro, self.chamadas = list(roteiro), []
        self.messages = SimpleNamespace(create=self._criar)

    def _criar(self, **kwargs):
        self.chamadas.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        return self.roteiro.pop(0)


@pytest.fixture(autouse=True)
def _ambiente(settings):
    cache.clear()
    settings.ANTHROPIC_API_KEY = "chave-de-teste"
    yield
    cache.clear()


@pytest.fixture
def parcela(cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="157.50", num_parcelas=3,
                       juros_diario=Decimal("5.00"))
    return Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("157.50"),
                                     data_vencimento=timezone.localdate() - datetime.timedelta(days=1))


def _enviar(auth_client, monkeypatch, roteiro, texto="oi"):
    falso = _FalsoClaude(roteiro)
    monkeypatch.setattr(servico, "_cliente_api", lambda: falso)
    resposta = auth_client.post(reverse("assistente:enviar"), json.dumps({"texto": texto}), content_type="application/json")
    return resposta, falso


def test_proposta_de_pagamento_so_grava_depois_de_confirmar(auth_client, parcela, monkeypatch):
    ct = parcela.contrato
    resposta, falso = _enviar(auth_client, monkeypatch, [
        _resposta(_ferramenta("registrar_pagamento", contrato_id=ct.pk, valor_pago="157.50", juros_pago="5.00", forma="pix"), parou="tool_use"),
        _resposta(_texto("Deixei a proposta pronta para confirmar.")),
    ], "Roberto pagou 162,50 no pix")
    dados = resposta.json()
    assert resposta.status_code == 200 and "proposta" in dados["resposta"].lower()
    assert len(dados["acoes"]) == 1 and dados["acoes"][0]["estado"] == "pendente"
    assert Pagamento.objects.count() == 0  # nada gravado ainda

    acao = Acao.objects.get()
    confirmada = auth_client.post(reverse("assistente:confirmar", args=[acao.pk]))
    assert confirmada.status_code == 200 and confirmada.json()["estado"] == "confirmada"
    pagamento = Pagamento.objects.get()
    assert pagamento.valor_pago == Decimal("157.50") and pagamento.juros_pago == Decimal("5.00") and pagamento.forma == "pix"
    assert "assistente" in pagamento.observacao.lower()
    parcela.refresh_from_db()
    assert parcela.status == "pago"
    assert auth_client.post(reverse("assistente:confirmar", args=[acao.pk])).status_code == 409  # não grava duas vezes


def test_cancelar_nao_grava_e_avisa_o_claude(auth_client, parcela, monkeypatch):
    ct = parcela.contrato
    _enviar(auth_client, monkeypatch, [
        _resposta(_ferramenta("registrar_pagamento", contrato_id=ct.pk, valor_pago="157.50"), parou="tool_use"),
        _resposta(_texto("ok")),
    ])
    acao = Acao.objects.get()
    assert auth_client.post(reverse("assistente:cancelar", args=[acao.pk])).json()["estado"] == "cancelada"
    assert Pagamento.objects.count() == 0
    assert "CANCELADA" in acao.conversa.mensagens[-1]["content"]


def test_ferramenta_de_leitura_responde_na_hora(auth_client, cliente, parcela, monkeypatch):
    resposta, falso = _enviar(auth_client, monkeypatch, [
        _resposta(_ferramenta("buscar_cliente", texto=cliente.nome[:4]), parou="tool_use"),
        _resposta(_texto("Achei.")),
    ])
    assert resposta.json()["resposta"] == "Achei." and resposta.json()["acoes"] == []
    resultado = falso.chamadas[1][-1]["content"][0]
    assert resultado["type"] == "tool_result" and cliente.nome in resultado["content"] and not resultado.get("is_error")


def test_parcela_ja_paga_vira_erro_para_o_claude_e_nao_cria_proposta(auth_client, parcela, monkeypatch):
    Pagamento(contrato=parcela.contrato, vencimento=parcela, data_pagamento=timezone.localdate(),
              valor_pago=Decimal("157.50"), forma="pix").registrar()
    _enviar(auth_client, monkeypatch, [
        _resposta(_ferramenta("registrar_pagamento", contrato_id=parcela.contrato.pk, valor_pago="157.50"), parou="tool_use"),
        _resposta(_texto("Essa parcela já foi paga.")),
    ])
    assert Acao.objects.count() == 0


def test_sem_chave_a_api_responde_que_nao_esta_configurado(auth_client, settings):
    settings.ANTHROPIC_API_KEY = ""
    resposta = auth_client.post(reverse("assistente:enviar"), json.dumps({"texto": "oi"}), content_type="application/json")
    assert resposta.status_code == 503 and "configurado" in resposta.json()["erro"]


def test_acao_de_outro_usuario_nao_e_acessivel(auth_client, parcela, monkeypatch, django_user_model):
    from apps.assistente.models import Conversa

    outro = django_user_model.objects.create_user(username="outro", email="outro@example.com", password="x" * 12)
    alheia = Acao.objects.create(conversa=Conversa.objects.create(usuario=outro), ferramenta="registrar_bloqueio",
                                 parametros={"contrato_id": parcela.contrato.pk, "observacao": ""}, resumo="x")
    assert auth_client.post(reverse("assistente:confirmar", args=[alheia.pk])).status_code == 404


def test_historico_traz_conversa_e_propostas_pendentes(auth_client, parcela, monkeypatch):
    _enviar(auth_client, monkeypatch, [
        _resposta(_ferramenta("registrar_pagamento", contrato_id=parcela.contrato.pk, valor_pago="157.50"), parou="tool_use"),
        _resposta(_texto("Proposta pronta.")),
    ], "Roberto pagou 157,50")
    dados = auth_client.get(reverse("assistente:historico")).json()
    assert dados["configurado"] is True
    assert [m["papel"] for m in dados["mensagens"]] == ["usuario", "assistente"]
    assert len(dados["pendentes"]) == 1 and dados["pendentes"][0]["confirmar_url"].endswith("/confirmar/")


def test_balao_aparece_nas_telas_para_quem_esta_logado(auth_client):
    html = auth_client.get(reverse("pagamentos:conexoes")).content.decode()
    assert 'id="assistente-abrir"' in html and "assistente.js" in html


def test_nova_conversa_cancela_propostas_pendentes(auth_client, parcela, monkeypatch):
    _enviar(auth_client, monkeypatch, [
        _resposta(_ferramenta("registrar_bloqueio", contrato_id=parcela.contrato.pk), parou="tool_use"),
        _resposta(_texto("ok")),
    ])
    assert auth_client.post(reverse("assistente:nova")).json() == {"ok": True}
    assert Acao.objects.get().estado == "cancelada"
    assert auth_client.get(reverse("assistente:historico")).json()["mensagens"] == []


@pytest.mark.parametrize("codigo, mensagem, esperado", [
    (400, "Your credit balance is too low to access the Anthropic API.", "sem saldo"),
    (401, "invalid x-api-key", "chave da API foi recusada"),
    (404, "model: nao-existe", "não está disponível"),
])
def test_erro_da_api_vira_mensagem_clara(auth_client, monkeypatch, codigo, mensagem, esperado):
    import anthropic
    import httpx2 as httpx

    class _Quebrado:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._criar)

        def _criar(self, **kwargs):
            requisicao = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIStatusError(mensagem, response=httpx.Response(codigo, request=requisicao), body=None)

    monkeypatch.setattr(servico, "_cliente_api", lambda: _Quebrado())
    resposta = auth_client.post(reverse("assistente:enviar"), json.dumps({"texto": "oi"}), content_type="application/json")
    assert resposta.status_code == 503 and esperado in resposta.json()["erro"]
