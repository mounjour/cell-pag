"""Cliente com grupo do WhatsApp: cobrança e avisos vão para o grupo; comprovante no grupo só vale se for do cliente."""

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.clientes.forms import ClienteForm
from apps.clientes.models import Cliente, valida_grupo_whatsapp
from apps.pagamentos import cobranca, comprovantes, whatsapp
from apps.pagamentos.models import Cobranca, ComprovanteRecebido
from apps.pagamentos.test_cobrancas import _contrato, cliente_cobranca  # noqa: F401  (cliente_cobranca é fixture)

GRUPO = "120363012345678901@g.us"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def test_validacao_do_identificador_do_grupo():
    valida_grupo_whatsapp(GRUPO)
    valida_grupo_whatsapp("5588999990000-1500000000@g.us")  # formato antigo
    valida_grupo_whatsapp("")
    for ruim in ("5588999991234", "grupo@g.us", "120363012345678901@s.whatsapp.net"):
        with pytest.raises(ValidationError):
            valida_grupo_whatsapp(ruim)


def test_destino_e_o_grupo_quando_ha_e_o_telefone_quando_nao(cliente_cobranca):
    assert cliente_cobranca.destino_whatsapp == "5583999991234"
    cliente_cobranca.grupo_whatsapp = GRUPO
    assert cliente_cobranca.destino_whatsapp == GRUPO


def test_cobranca_vai_para_o_grupo_e_apagar_usa_o_identificador_do_grupo(cliente_cobranca, settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    settings.CORA_PROVIDER = "log"
    cliente_cobranca.grupo_whatsapp = GRUPO
    cliente_cobranca.save()
    enviadas = []
    monkeypatch.setattr(cobranca, "enviar_mensagem", lambda **kw: enviadas.append(kw) or {"simulado": False, "id": "m1"})
    monkeypatch.setattr(cobranca, "enviar_imagem", lambda **kw: enviadas.append(kw) or {"simulado": False, "id": "m1"})
    contrato = _contrato(cliente_cobranca, timezone.localdate(), atraso=2)

    nivel, _ = cobranca.enviar_agora(contrato)
    assert nivel == "success" and {e["destinatario"] for e in enviadas} == {GRUPO}
    assert Cobranca.objects.get(contrato=contrato).destinatario == GRUPO  # cabe no campo (mais de 20 caracteres)

    chamadas = []
    monkeypatch.setattr(whatsapp, "_chamar_evolution", lambda caminho, corpo, metodo="POST": chamadas.append(corpo) or {})
    whatsapp.apagar_mensagem(destinatario=GRUPO, id_mensagem="m1")
    whatsapp.apagar_mensagem(destinatario="5583999991234", id_mensagem="m2")
    assert [c["remoteJid"] for c in chamadas] == [GRUPO, "5583999991234@s.whatsapp.net"]


def _arquivo(grupo=GRUPO, participante="5583999991234@s.whatsapp.net", id_="ABC1", de_mim=False):
    chave = {"remoteJid": grupo, "fromMe": de_mim, "id": id_}
    if participante:
        chave["participant"] = participante
    return {"key": chave, "message": {"imageMessage": {"caption": "comprovante"}}}


def test_comprovante_no_grupo_so_vale_se_quem_mandou_for_o_cliente(cliente_cobranca, monkeypatch):
    cliente_cobranca.grupo_whatsapp = GRUPO
    cliente_cobranca.save()
    monkeypatch.setattr(comprovantes, "conferir_na_cora", lambda c: False)
    monkeypatch.setattr(comprovantes, "_avisar_cliente_que_ainda_nao_caiu", lambda c: None)

    assert comprovantes.processar_mensagem_recebida(_arquivo(participante="5583988880000@s.whatsapp.net", id_="B1")) is None  # financeiro
    assert comprovantes.processar_mensagem_recebida(_arquivo(participante=None, id_="B2")) is None  # sem número de quem mandou
    assert comprovantes.processar_mensagem_recebida(_arquivo(grupo="120363999999999999@g.us", id_="B3")) is None  # grupo desconhecido
    assert comprovantes.processar_mensagem_recebida(_arquivo(de_mim=True, id_="B4")) is None  # enviada pela empresa
    assert not ComprovanteRecebido.objects.exists()

    recebido = comprovantes.processar_mensagem_recebida(_arquivo(id_="B5"))
    assert recebido is not None and recebido.cliente == cliente_cobranca
    # o 9 a mais ou a menos do celular também é reconhecido
    assert comprovantes.processar_mensagem_recebida(_arquivo(participante="558399991234@s.whatsapp.net", id_="B6")) is not None


def test_aviso_de_comprovante_vai_para_o_grupo(cliente_cobranca, monkeypatch):
    cliente_cobranca.grupo_whatsapp = GRUPO
    cliente_cobranca.save()
    enviadas = []
    monkeypatch.setattr(comprovantes, "enviar_mensagem", lambda **kw: enviadas.append(kw["destinatario"]) or {"simulado": False, "id": "x"})
    monkeypatch.setattr(comprovantes, "conferir_na_cora", lambda c: False)
    comprovantes.processar_mensagem_recebida(_arquivo(id_="C1"))
    assert enviadas == [GRUPO]


def test_grupos_do_whatsapp_lista_ordenada_ignora_o_que_nao_e_grupo_e_usa_cache(settings, monkeypatch):
    assert whatsapp.grupos_do_whatsapp() is None  # modo simulação
    settings.WHATSAPP_PROVIDER = "evolution"
    chamadas = []
    monkeypatch.setattr(
        whatsapp, "_chamar_evolution_get",
        lambda caminho, consulta=None: chamadas.append((caminho, consulta)) or [
            {"id": "120363000000000002@g.us", "subject": "Zeca + Financeiro", "size": 3},
            {"id": "120363000000000001@g.us", "subject": "Ana + Financeiro", "size": 3},
            {"id": "5583999990000@s.whatsapp.net", "subject": "não é grupo"},
        ],
    )
    grupos = whatsapp.grupos_do_whatsapp()
    assert [g["nome"] for g in grupos] == ["Ana + Financeiro", "Zeca + Financeiro"] and grupos[0]["participantes"] == 3
    whatsapp.grupos_do_whatsapp()
    assert chamadas == [("/group/fetchAllGroups", {"getParticipants": "false"})]  # a segunda veio do cache

    def _falha(*a, **k):
        raise whatsapp.WhatsAppErro("fora do ar")

    cache.clear()
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", _falha)
    assert whatsapp.grupos_do_whatsapp() is None


def _dados_cliente(**extra):
    return {"nome": "Maria Souza", "cpf": "52998224725", "telefone_whatsapp": "88999990000", "endereco": "", **extra}


def test_formulario_sem_lista_aceita_o_identificador_digitado_e_recusa_lixo():
    form = ClienteForm(_dados_cliente(grupo_whatsapp=GRUPO))
    assert form.is_valid(), form.errors
    assert not ClienteForm(_dados_cliente(grupo_whatsapp="meu grupo")).is_valid()


def test_formulario_com_lista_escolhe_o_grupo_pelo_nome_e_limpa_ao_tirar(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", lambda c, q=None: [{"id": GRUPO, "subject": "Maria + Financeiro", "size": 3}])
    form = ClienteForm(_dados_cliente(grupo_whatsapp=GRUPO))
    assert "Maria + Financeiro (3 participantes)" in [rotulo for _, rotulo in form.fields["grupo_whatsapp"].choices]
    assert form.is_valid(), form.errors
    cliente = form.save()
    assert cliente.grupo_whatsapp == GRUPO and cliente.grupo_whatsapp_nome == "Maria + Financeiro"
    assert not ClienteForm(_dados_cliente(cpf="11144477735", grupo_whatsapp="120363000000000009@g.us")).is_valid()  # fora da lista

    sem = ClienteForm(_dados_cliente(grupo_whatsapp=""), instance=cliente)
    assert sem.is_valid()
    assert sem.save().grupo_whatsapp_nome == ""


def test_tela_do_cliente_mostra_o_grupo(auth_client):
    cliente = Cliente.objects.create(
        nome="Maria", cpf="52998224725", telefone_whatsapp="+5588999990000", grupo_whatsapp=GRUPO, grupo_whatsapp_nome="Maria + Financeiro",
    )
    html = auth_client.get(reverse("clientes:detalhe", args=[cliente.pk])).content.decode()
    assert "Maria + Financeiro" in html and "vão para este grupo" in html


# ── diagnóstico: o que a Evolution devolve ───────────────────────────────────

def test_consultar_grupos_conta_o_que_chegou_e_o_que_foi_ignorado(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    monkeypatch.setattr(
        whatsapp, "_chamar_evolution_get",
        lambda caminho, consulta=None: [
            {"id": GRUPO, "subject": "Maria + Financeiro", "size": 3},
            {"id": "5583999990000@s.whatsapp.net", "subject": "contato"},
            "lixo",
        ],
    )
    r = whatsapp.consultar_grupos()
    assert r["recebidos"] == 3 and [g["nome"] for g in r["grupos"]] == ["Maria + Financeiro"] and len(r["ignorados"]) == 2
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", lambda c, q=None: {"error": True})
    assert "não é uma lista" in whatsapp.consultar_grupos()["ignorados"][0]


def test_lista_de_grupos_dura_um_minuto_e_pode_ser_forcada(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    chamadas = []
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", lambda c, q=None: chamadas.append(1) or [{"id": GRUPO, "subject": "A", "size": 3}])
    whatsapp.grupos_do_whatsapp()
    whatsapp.grupos_do_whatsapp()
    assert len(chamadas) == 1
    whatsapp.grupos_do_whatsapp(forcar=True)
    assert len(chamadas) == 2


def test_tela_de_diagnostico_mostra_os_grupos_e_quem_usa(auth_client, settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    grupos = [{"id": GRUPO, "subject": "Maria + Financeiro", "size": 3}, {"id": "120363000000000009@g.us", "subject": "Outro", "size": 83}]
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", lambda c, q=None: grupos if "fetchAllGroups" in c else {"instance": {"state": "open"}})
    Cliente.objects.create(nome="Maria", cpf="52998224725", telefone_whatsapp="+5588999990000", grupo_whatsapp=GRUPO)
    html = auth_client.get(reverse("pagamentos:grupos_whatsapp")).content.decode()
    assert "devolveu <strong>2</strong>" in html and "Maria + Financeiro" in html and GRUPO in html
    assert "<td>Maria</td>" in html  # o cliente que já usa o grupo aparece na linha dele
    assert "Maria + Financeiro" in html and "Outro" in html


def test_tela_de_diagnostico_mostra_o_erro_da_evolution(auth_client, settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"

    def _falha(c, q=None):
        if "fetchAllGroups" in c:
            raise whatsapp.WhatsAppErro("Falha de comunicação com a Evolution API.")
        return {"instance": {"state": "open"}}

    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", _falha)
    assert "A Evolution não respondeu" in auth_client.get(reverse("pagamentos:grupos_whatsapp")).content.decode()


def test_tela_de_diagnostico_exige_login(client):
    assert client.get(reverse("pagamentos:grupos_whatsapp")).status_code == 302
