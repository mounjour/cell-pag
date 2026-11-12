"""Grupos conhecidos pelas mensagens que chegam (a lista da Evolution pode vir incompleta)."""

import json

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.clientes.forms import ClienteForm
from apps.clientes.models import Cliente
from apps.pagamentos import grupos, whatsapp
from apps.pagamentos.models import GrupoWhatsApp

GRUPO_A = "120363012345678901@g.us"
GRUPO_B = "120363098765432109@g.us"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def _mensagem(jid, id_="X1"):
    return {"key": {"remoteJid": jid, "fromMe": False, "id": id_, "participant": "5588999990000@s.whatsapp.net"}, "message": {"conversation": "oi"}}


def test_registra_so_o_identificador_do_grupo_e_conta_as_mensagens():
    assert grupos.registrar_grupo_visto(_mensagem(GRUPO_A)) is True
    assert grupos.registrar_grupo_visto(_mensagem(GRUPO_A, "X2")) is True
    assert grupos.registrar_grupo_visto(_mensagem("5588999990000@s.whatsapp.net")) is False  # conversa individual
    assert grupos.registrar_grupo_visto("lixo") is False and grupos.registrar_grupo_visto({"key": None}) is False
    g = GrupoWhatsApp.objects.get()
    assert g.jid == GRUPO_A and g.mensagens == 2 and g.nome == ""
    assert not hasattr(g, "conteudo")  # nada do conteúdo é guardado


def test_nome_vem_do_findgroupinfos_e_falha_em_silencio(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    grupos.registrar_grupo_visto(_mensagem(GRUPO_A))
    grupos.registrar_grupo_visto(_mensagem(GRUPO_B))
    consultas = []

    def _info(caminho, consulta=None):
        consultas.append((caminho, consulta))
        if consulta["groupJid"] == GRUPO_B:
            raise whatsapp.WhatsAppErro("fora do ar")
        return {"id": GRUPO_A, "subject": "Maria + Financeiro", "size": 3}

    monkeypatch.setattr(grupos, "_chamar_evolution_get", _info)
    grupos.completar_nomes()
    assert GrupoWhatsApp.objects.get(jid=GRUPO_A).nome == "Maria + Financeiro" and GrupoWhatsApp.objects.get(jid=GRUPO_A).participantes == 3
    assert GrupoWhatsApp.objects.get(jid=GRUPO_B).nome == ""
    assert all(c[0] == "/group/findGroupInfos" for c in consultas)


def test_webhook_de_mensagem_de_grupo_anota_o_grupo(client, settings):
    settings.EVOLUTION_WEBHOOK_TOKEN = "segredo-de-teste"
    corpo = {"event": "messages.upsert", "data": _mensagem(GRUPO_A)}
    r = client.post(reverse("pagamentos:whatsapp_webhook"), json.dumps(corpo), content_type="application/json", HTTP_APIKEY="segredo-de-teste")
    assert r.status_code == 200 and GrupoWhatsApp.objects.filter(jid=GRUPO_A).exists()


def test_lista_do_cadastro_inclui_o_grupo_visto_que_a_evolution_nao_listou(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    grupos.registrar_grupo_visto(_mensagem(GRUPO_A))

    def _get(caminho, consulta=None):
        if "fetchAllGroups" in caminho:
            return [{"id": GRUPO_B, "subject": "Outro", "size": 83}]
        return {"subject": "Maria + Financeiro", "size": 3}

    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", _get)
    monkeypatch.setattr(grupos, "_chamar_evolution_get", _get)
    lista = whatsapp.grupos_do_whatsapp()
    assert {g["id"]: g["nome"] for g in lista} == {GRUPO_B: "Outro", GRUPO_A: "Maria + Financeiro"}


def test_formulario_aceita_o_identificador_colado_e_recusa_lixo(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", lambda c, q=None: [{"id": GRUPO_B, "subject": "Outro", "size": 83}])
    GrupoWhatsApp.objects.create(jid=GRUPO_A, nome="Maria + Financeiro", visto_em="2026-11-12T10:00:00Z")
    dados = {"nome": "Maria", "cpf": "52998224725", "telefone_whatsapp": "88999990000", "endereco": "", "grupo_whatsapp": ""}
    form = ClienteForm({**dados, "grupo_whatsapp_manual": GRUPO_A})
    assert form.is_valid(), form.errors
    cliente = form.save()
    assert cliente.grupo_whatsapp == GRUPO_A and cliente.grupo_whatsapp_nome == "Maria + Financeiro"
    ruim = ClienteForm({**dados, "cpf": "11144477735", "grupo_whatsapp_manual": "grupo qualquer"})
    assert not ruim.is_valid() and "grupo_whatsapp_manual" in ruim.errors


def test_tela_de_diagnostico_lista_os_grupos_vistos(auth_client, settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    grupos.registrar_grupo_visto(_mensagem(GRUPO_A))
    Cliente.objects.create(nome="Maria", cpf="52998224725", telefone_whatsapp="+5588999990000", grupo_whatsapp=GRUPO_A)

    def _get(caminho, consulta=None):
        if "fetchAllGroups" in caminho:
            return [{"id": GRUPO_B, "subject": "Outro", "size": 83}]
        if "findGroupInfos" in caminho:
            return {"subject": "Maria + Financeiro", "size": 3}
        return {"instance": {"state": "open"}}

    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", _get)
    monkeypatch.setattr(grupos, "_chamar_evolution_get", _get)
    html = auth_client.get(reverse("pagamentos:grupos_whatsapp")).content.decode()
    assert "Grupos de onde chegaram mensagens" in html and "Maria + Financeiro" in html and GRUPO_A in html
    assert "<td>não</td>" in html and "Maria" in html  # não está na lista da Evolution e já é usado por um cliente
