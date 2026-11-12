"""Quando a conexão do WhatsApp cai: reiniciar sem QR, tentar de novo na rotina e avisar."""

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.pagamentos import cobranca, whatsapp
from apps.pagamentos.models import Cobranca
from apps.pagamentos.test_cobrancas import _contrato, cliente_cobranca  # noqa: F401  (cliente_cobranca é fixture)
from apps.pagamentos.whatsapp import WhatsAppErro

CONEXAO_CAIDA = "A Evolution recusou a operação (HTTP 500). Motivo: ['Error: Connection Closed']"


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


# ── whatsapp.reiniciar_conexao ────────────────────────────────────────────────

def test_conexao_caiu_reconhece_o_erro_da_conexao_morta():
    assert whatsapp.conexao_caiu(WhatsAppErro(CONEXAO_CAIDA))
    assert not whatsapp.conexao_caiu(WhatsAppErro("A Evolution recusou a operação (HTTP 400). O número não tem WhatsApp."))


def test_reiniciar_usa_o_restart_sem_perder_a_sessao(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    chamadas = []
    monkeypatch.setattr(whatsapp, "_chamar_evolution", lambda caminho, corpo, metodo="POST": chamadas.append((caminho, metodo)) or {"instance": {"status": "open"}})
    assert whatsapp.reiniciar_conexao() == "reiniciada"
    assert chamadas == [("/instance/restart", "POST")]  # nada de logout


def test_reiniciar_pede_a_reconexao_quando_a_evolution_ja_sabe_que_caiu(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"

    def _restart(caminho, corpo, metodo="POST"):
        raise WhatsAppErro("A Evolution recusou a operação (HTTP 400). Motivo: ['The \"celulares\" instance is not connected']")

    visto = []
    monkeypatch.setattr(whatsapp, "_chamar_evolution", _restart)
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", lambda caminho, consulta=None: visto.append(caminho) or {"count": 0})
    assert whatsapp.reiniciar_conexao() == "reconectada" and visto == ["/instance/connect"]


def test_reiniciar_repassa_outros_erros_e_o_erro_dentro_do_corpo(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"

    def _falha(caminho, corpo, metodo="POST"):
        raise WhatsAppErro("Falha de comunicação com a Evolution API.")

    monkeypatch.setattr(whatsapp, "_chamar_evolution", _falha)
    with pytest.raises(WhatsAppErro, match="comunicação"):
        whatsapp.reiniciar_conexao()
    monkeypatch.setattr(whatsapp, "_chamar_evolution", lambda c, b, metodo="POST": {"error": True, "message": "Error: boom"})
    with pytest.raises(WhatsAppErro, match="não conseguiu reiniciar"):
        whatsapp.reiniciar_conexao()
    settings.WHATSAPP_PROVIDER = "log"
    with pytest.raises(WhatsAppErro, match="simulação"):
        whatsapp.reiniciar_conexao()


# ── a rotina se recupera sozinha ─────────────────────────────────────────────

@pytest.fixture
def evolution(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    settings.CORA_PROVIDER = "log"
    monkeypatch.setattr(cobranca.time, "sleep", lambda s: None)
    return settings


def test_envio_que_falha_por_conexao_morta_reinicia_e_tenta_de_novo(cliente_cobranca, evolution, monkeypatch):
    reinicios, tentativas = [], []

    def _envia(**kw):
        tentativas.append(kw["destinatario"])
        if len(tentativas) == 1:
            raise WhatsAppErro(CONEXAO_CAIDA)
        return {"simulado": False, "id": "m1"}

    monkeypatch.setattr(cobranca, "enviar_mensagem", _envia)
    monkeypatch.setattr(cobranca, "enviar_imagem", _envia)
    monkeypatch.setattr(cobranca, "reiniciar_conexao", lambda: reinicios.append(1) or "reiniciada")
    _contrato(cliente_cobranca, timezone.localdate(), atraso=2)

    resultado = cobranca.processar_cobrancas()
    assert reinicios == [1] and len(tentativas) >= 2
    assert resultado["enviadas"] == 1 and resultado["erros"] == 0 and resultado["reiniciou_conexao"] is True
    assert Cobranca.objects.get().status == Cobranca.Status.ENVIADO


def test_so_reinicia_uma_vez_por_rotina_e_nao_reinicia_por_outros_erros(cliente_cobranca, evolution, monkeypatch):
    from apps.clientes.models import Cliente
    from validate_docbr import CPF as CPFGen

    reinicios = []

    def _sempre_cai(**kw):
        raise WhatsAppErro(CONEXAO_CAIDA)

    monkeypatch.setattr(cobranca, "enviar_mensagem", _sempre_cai)
    monkeypatch.setattr(cobranca, "enviar_imagem", _sempre_cai)
    monkeypatch.setattr(cobranca, "reiniciar_conexao", lambda: reinicios.append(1) or "reiniciada")
    hoje = timezone.localdate()
    _contrato(cliente_cobranca, hoje, atraso=2)
    outro = Cliente.objects.create(nome="Joao", cpf=CPFGen().generate(), telefone_whatsapp="+5583988887777")
    _contrato(outro, hoje, atraso=3)

    resultado = cobranca.processar_cobrancas()
    assert len(reinicios) == 1  # depois de reiniciar uma vez, as outras não tentam de novo
    assert resultado["erros"] == 2 and Cobranca.objects.filter(status=Cobranca.Status.ERRO).count() == 2

    reinicios.clear()
    monkeypatch.setattr(cobranca, "enviar_mensagem", lambda **kw: (_ for _ in ()).throw(WhatsAppErro("A Evolution recusou a operação (HTTP 400). O número não tem WhatsApp.")))
    monkeypatch.setattr(cobranca, "enviar_imagem", cobranca.enviar_mensagem)
    Cobranca.objects.all().delete()
    cobranca.processar_cobrancas()
    assert reinicios == []  # erro de número não é queda da conexão


def test_se_o_reinicio_falhar_o_erro_original_e_registrado(cliente_cobranca, evolution, monkeypatch):
    def _cai(**kw):
        raise WhatsAppErro(CONEXAO_CAIDA)

    def _nao_reinicia():
        raise WhatsAppErro("A Evolution recusou a operação (HTTP 500).")

    monkeypatch.setattr(cobranca, "enviar_mensagem", _cai)
    monkeypatch.setattr(cobranca, "enviar_imagem", _cai)
    monkeypatch.setattr(cobranca, "reiniciar_conexao", _nao_reinicia)
    _contrato(cliente_cobranca, timezone.localdate(), atraso=2)
    cobranca.processar_cobrancas()
    c = Cobranca.objects.get()
    assert c.status == Cobranca.Status.ERRO and "Connection Closed" in c.erro


def test_rotina_diz_o_que_aconteceu_na_falha(cliente_cobranca, evolution, monkeypatch):
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    def _cai(**kw):
        raise WhatsAppErro(CONEXAO_CAIDA)

    monkeypatch.setattr(cobranca, "enviar_mensagem", _cai)
    monkeypatch.setattr(cobranca, "enviar_imagem", _cai)
    monkeypatch.setattr(cobranca, "reiniciar_conexao", lambda: "reiniciada")
    monkeypatch.setattr("apps.pagamentos.management.commands.enviar_cobrancas_clientes.reconciliar_abertas", lambda: {"consultadas": 0, "pagas": 0, "erros": 0})
    from apps.pagamentos.models import ConfiguracaoCobranca

    ConfiguracaoCobranca.definir(False, None)
    _contrato(cliente_cobranca, timezone.localdate(), atraso=2)
    saida = StringIO()
    with pytest.raises(CommandError, match=r"1 cobrança\(s\) com erro no WhatsApp"):
        call_command("enviar_cobrancas_clientes", stdout=saida)
    assert "reiniciada automaticamente" in saida.getvalue()


# ── telas e aviso ────────────────────────────────────────────────────────────

def test_botao_reiniciar_usa_o_restart_e_so_o_desconectar_faz_logout(auth_client, monkeypatch):
    chamadas = []
    monkeypatch.setattr(whatsapp, "reiniciar_conexao", lambda: chamadas.append("restart") or "reiniciada")
    monkeypatch.setattr(whatsapp, "desconectar_sessao", lambda: chamadas.append("logout"))
    resposta = auth_client.post(reverse("pagamentos:conexoes_reiniciar"), follow=True)
    assert chamadas == ["restart"] and "Conexão reiniciada" in resposta.content.decode()


def test_botao_reiniciar_mostra_o_erro_e_sugere_o_ultimo_recurso(auth_client, monkeypatch):
    def _falha():
        raise WhatsAppErro("A Evolution recusou a operação (HTTP 500).")

    monkeypatch.setattr(whatsapp, "reiniciar_conexao", _falha)
    html = auth_client.post(reverse("pagamentos:conexoes_reiniciar"), follow=True).content.decode()
    assert "Não consegui reiniciar a conexão" in html and "Desconectar e ler o QR de novo" in html


def test_notificacao_de_cobrancas_com_erro_hoje(auth_client, cliente_cobranca):
    contrato = _contrato(cliente_cobranca, timezone.localdate(), atraso=1)
    assert "com erro no WhatsApp" not in auth_client.get(reverse("relatorios:inicio")).content.decode()
    Cobranca.objects.create(
        contrato=contrato, vencimento=contrato.vencimentos.get(), data_alvo=timezone.localdate(), destinatario="5583", mensagem="x",
        status=Cobranca.Status.ERRO, erro=CONEXAO_CAIDA,
    )
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert "1 cobrança de hoje com erro no WhatsApp" in html and "grupo=erro" in html
    tela = auth_client.get(reverse("pagamentos:mensagens"), follow=True).content.decode()
    assert "de hoje com erro no WhatsApp" in tela and "reinicie a conexão em Conexões" in tela
