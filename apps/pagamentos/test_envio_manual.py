import datetime
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.pagamentos import cobranca, views
from apps.pagamentos.models import Cobranca, QrWhatsApp
from apps.pagamentos.test_cobrancas import _contrato, cliente_cobranca  # noqa: F401  (cliente_cobranca é fixture)
from apps.pagamentos.whatsapp import WhatsAppErro


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def evolution(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    settings.CORA_PROVIDER = "log"
    enviadas = []
    monkeypatch.setattr("apps.pagamentos.cobranca.enviar_mensagem", lambda **kw: enviadas.append(kw) or {"simulado": False, "id": "m1"})
    monkeypatch.setattr("apps.pagamentos.cobranca.enviar_imagem", lambda **kw: enviadas.append(kw) or {"simulado": False, "id": "m1"})
    return enviadas


@pytest.mark.django_db
def test_botao_envia_a_cobranca_de_hoje_uma_vez_so(auth_client, cliente_cobranca, evolution):
    contrato = _contrato(cliente_cobranca, timezone.localdate(), atraso=2)
    url = reverse("pagamentos:cobranca_enviar", args=[contrato.pk])
    resposta = auth_client.post(url, follow=True)
    assert "Cobrança enviada no WhatsApp de Maria da Silva" in resposta.content.decode()
    assert Cobranca.objects.get(contrato=contrato).status == Cobranca.Status.ENVIADO
    assert len(evolution) >= 1
    n = len(evolution)
    de_novo = auth_client.post(url, follow=True)
    assert "já foi enviada" in de_novo.content.decode()
    assert len(evolution) == n


@pytest.mark.django_db
def test_botao_mostra_o_motivo_quando_a_evolution_falha(auth_client, cliente_cobranca, evolution, monkeypatch):
    def _falha(**kw):
        raise WhatsAppErro("A Evolution recusou a operação (HTTP 500). Motivo: Connection Closed")

    monkeypatch.setattr("apps.pagamentos.cobranca.enviar_mensagem", _falha)
    monkeypatch.setattr("apps.pagamentos.cobranca.enviar_imagem", _falha)
    contrato = _contrato(cliente_cobranca, timezone.localdate(), atraso=1)
    resposta = auth_client.post(reverse("pagamentos:cobranca_enviar", args=[contrato.pk]), follow=True)
    assert "Connection Closed" in resposta.content.decode()
    assert Cobranca.objects.get(contrato=contrato).status == Cobranca.Status.ERRO


@pytest.mark.django_db
def test_contrato_fora_da_cobranca_de_hoje_nao_envia(auth_client, cliente_cobranca, evolution):
    contrato = _contrato(cliente_cobranca, timezone.localdate() + datetime.timedelta(days=10))
    resposta = auth_client.post(reverse("pagamentos:cobranca_enviar", args=[contrato.pk]), follow=True)
    assert "não está na cobrança de hoje" in resposta.content.decode()
    assert evolution == []


@pytest.mark.django_db
def test_enviar_agora_nao_manda_para_pix_cancelado(cliente_cobranca, evolution):
    from apps.pagamentos.pix_cora import suspender_cobranca

    contrato = _contrato(cliente_cobranca, timezone.localdate(), atraso=1)
    suspender_cobranca(contrato.vencimentos.get())
    nivel, texto = cobranca.enviar_agora(contrato)
    assert nivel == "error" and "suspensa" in texto
    assert evolution == []


def test_botao_exige_login(client):
    assert client.post(reverse("pagamentos:cobranca_enviar", args=[1])).status_code == 302


@pytest.mark.django_db
def test_desconectar_faz_logout_e_ja_pede_o_qr(auth_client, monkeypatch):
    chamadas = []
    monkeypatch.setattr("apps.pagamentos.whatsapp.desconectar_sessao", lambda: chamadas.append("logout"))
    QrWhatsApp.guardar("data:image/png;base64,AAA", timezone.now())
    resposta = auth_client.post(reverse("pagamentos:conexoes_desconectar"))
    assert chamadas == ["logout"] and resposta.status_code == 302
    assert "Sessão do WhatsApp descartada" in [str(m) for m in get_messages(resposta.wsgi_request)][0]
    assert QrWhatsApp.atual() is None
    assert views.CHAVE_SESSAO_QR_ATIVO in auth_client.session


@pytest.mark.django_db
def test_desconectar_mostra_o_erro_da_evolution(auth_client, monkeypatch):
    def _falha():
        raise WhatsAppErro("Falha de comunicação com a Evolution API.")

    monkeypatch.setattr("apps.pagamentos.whatsapp.desconectar_sessao", _falha)
    resposta = auth_client.post(reverse("pagamentos:conexoes_desconectar"), follow=True)
    assert "Não consegui desconectar a sessão" in resposta.content.decode()


def test_logout_usa_delete_na_evolution(settings, monkeypatch):
    from apps.pagamentos import whatsapp

    settings.WHATSAPP_PROVIDER = "evolution"
    visto = {}
    monkeypatch.setattr(whatsapp, "_chamar_evolution", lambda caminho, corpo, metodo="POST": visto.update(caminho=caminho, metodo=metodo) or {})
    whatsapp.desconectar_sessao()
    assert visto == {"caminho": "/instance/logout", "metodo": "DELETE"}
    settings.WHATSAPP_PROVIDER = "log"
    with pytest.raises(WhatsAppErro):
        whatsapp.desconectar_sessao()


@pytest.mark.django_db
def test_botoes_aparecem_nas_telas(auth_client, cliente_cobranca, evolution, monkeypatch):
    contrato = _contrato(cliente_cobranca, timezone.localdate(), atraso=2)
    cobrar = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert reverse("pagamentos:cobranca_enviar", args=[contrato.pk]) in cobrar and "Enviar cobrança" in cobrar
    cliente = auth_client.get(reverse("clientes:detalhe", args=[cliente_cobranca.pk])).content.decode()
    assert reverse("pagamentos:cobranca_enviar", args=[contrato.pk]) in cliente
    auth_client.post(reverse("pagamentos:cobranca_enviar", args=[contrato.pk]))
    depois = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert reverse("pagamentos:cobranca_enviar", args=[contrato.pk]) not in depois  # já enviada: some o botão
    monkeypatch.setattr("apps.pagamentos.badge.status_whatsapp_ao_vivo", lambda: "open")
    conexoes = auth_client.get(reverse("pagamentos:conexoes")).content.decode()
    assert reverse("pagamentos:conexoes_reiniciar") in conexoes and "Reiniciar a conexão" in conexoes
    assert reverse("pagamentos:conexoes_desconectar") in conexoes and "Desconectar e ler o QR de novo" in conexoes


# ── tela "Mensagens de cobrança" ──────────────────────────────────────────────

@pytest.mark.django_db
def test_tela_de_mensagens_mostra_enviadas_erros_e_quem_ficou_sem_mensagem(auth_client, cliente_cobranca, evolution, monkeypatch):
    from apps.clientes.models import Cliente
    from validate_docbr import CPF as CPFGen

    hoje = timezone.localdate()
    com_erro = _contrato(cliente_cobranca, hoje, atraso=3)
    outro = Cliente.objects.create(nome="Joao Souza", cpf=CPFGen().generate(), telefone_whatsapp="+5583988887777")
    enviado = _contrato(outro, hoje, atraso=2)
    Cobranca.objects.create(contrato=com_erro, vencimento=com_erro.vencimentos.get(), data_alvo=hoje, destinatario="5583", mensagem="x",
                            status=Cobranca.Status.ERRO, erro="A Evolution recusou a operação (HTTP 500). Motivo: Connection Closed", tentativas=2)
    Cobranca.objects.create(contrato=enviado, vencimento=enviado.vencimentos.get(), data_alvo=hoje, destinatario="5583", mensagem="x",
                            status=Cobranca.Status.ENVIADO, enviado_em=timezone.now(), tentativas=1)
    terceiro = Cliente.objects.create(nome="Pedro Lima", cpf=CPFGen().generate(), telefone_whatsapp="+5583977776666")
    _contrato(terceiro, hoje, atraso=1)

    html = auth_client.get(reverse("pagamentos:mensagens")).content.decode()
    assert "Connection Closed" in html and "Tentar de novo" in html
    assert "Joao Souza" in html and "Pedro Lima" in html and "Ainda sem mensagem" in html
    assert "Com erro (1)" in html and "Enviadas (1)" in html

    so_erro = auth_client.get(reverse("pagamentos:mensagens"), {"grupo": "erro"}).content.decode()
    assert "Maria da Silva" in so_erro and "Joao Souza" not in so_erro and "Pedro Lima" not in so_erro


@pytest.mark.django_db
def test_tela_de_mensagens_de_outro_dia_nao_oferece_reenvio(auth_client, cliente_cobranca):
    ontem = timezone.localdate() - datetime.timedelta(days=1)
    contrato = _contrato(cliente_cobranca, ontem)
    Cobranca.objects.create(contrato=contrato, vencimento=contrato.vencimentos.get(), data_alvo=ontem, destinatario="5583", mensagem="x",
                            status=Cobranca.Status.ERRO, erro="falhou")
    html = auth_client.get(reverse("pagamentos:mensagens"), {"data": ontem.isoformat()}).content.decode()
    assert "falhou" in html and "Tentar de novo" not in html
    assert auth_client.get(reverse("pagamentos:mensagens"), {"data": "lixo"}).status_code == 200


def test_tela_de_mensagens_exige_login(client):
    assert client.get(reverse("pagamentos:mensagens")).status_code == 302
