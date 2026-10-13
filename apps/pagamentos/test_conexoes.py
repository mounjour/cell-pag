import datetime

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.pagamentos.whatsapp import WhatsAppErro

BASE = datetime.datetime(2026, 10, 5, 12, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def test_status_exige_login(client):
    resposta = client.get(reverse("pagamentos:conexoes_status"))
    assert resposta.status_code == 302


@pytest.mark.django_db
def test_status_devolve_o_estado_do_whatsapp(auth_client, monkeypatch):
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "open")
    resposta = auth_client.get(reverse("pagamentos:conexoes_status"))
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": "open"}
    assert resposta["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_status_vira_erro_quando_a_evolution_nao_responde(auth_client, monkeypatch):
    def _falha():
        raise WhatsAppErro("fora do ar")

    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", _falha)
    resposta = auth_client.get(reverse("pagamentos:conexoes_status"))
    assert resposta.json() == {"estado": "erro"}


@pytest.mark.django_db
def test_status_usa_cache_curto_e_alimenta_o_do_menu(auth_client, monkeypatch):
    chamadas = []

    def _consulta():
        chamadas.append(1)
        return "close"

    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", _consulta)
    url = reverse("pagamentos:conexoes_status")
    auth_client.get(url)
    auth_client.get(url)
    assert len(chamadas) == 1
    assert cache.get("whatsapp_status") == "close"


@pytest.mark.django_db
def test_pagina_conexoes_tem_o_cartao_que_a_tela_atualiza(auth_client, monkeypatch):
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "open")
    html = auth_client.get(reverse("pagamentos:conexoes")).content.decode()
    assert "data-conexoes-card" in html
    assert 'data-conexoes-status-url="' in html


@pytest.fixture
def relogio(monkeypatch):
    """Relógio da tela de Conexões, em segundos a partir de BASE (para o QR e o pedido de QR)."""
    segundos = [1000.0]
    monkeypatch.setattr("apps.pagamentos.views._agora", lambda: BASE + datetime.timedelta(seconds=segundos[0]))
    return segundos


@pytest.fixture
def qr_pedido(auth_client, monkeypatch, relogio):
    """Cliente logado, WhatsApp desconectado e QR já pedido e gerado; devolve a lista de chamadas à Evolution."""
    chamadas = []

    def _qr():
        chamadas.append(1)
        return f"data:image/png;base64,QR{len(chamadas)}"

    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_qrcode", _qr)
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    auth_client.post(reverse("pagamentos:conexoes_qr"))
    return chamadas


@pytest.mark.django_db
def test_abrir_conexoes_nunca_pede_qr_a_evolution(auth_client, monkeypatch, relogio):
    """Era o motivo da demora: com o pedido ativo, cada visita gerava um QR na hora."""
    chamadas = []
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_qrcode", lambda: chamadas.append(1) or "data:x")
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))  # só registra o pedido: não espera a Evolution
    assert chamadas == []

    resposta = auth_client.get(reverse("pagamentos:conexoes"))
    assert chamadas == []  # a página abre sem esperar o QR
    assert resposta.context["gerando_qr"] is True and resposta.context["qr_code"] == ""
    html = resposta.content.decode()
    assert "data-qr-gerando" in html and reverse("pagamentos:conexoes_qr") in html


@pytest.mark.django_db
def test_sem_clique_a_pagina_so_oferece_o_botao(auth_client, monkeypatch, relogio):
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    resposta = auth_client.get(reverse("pagamentos:conexoes"))
    assert resposta.context["quer_qr"] is False and resposta.context["gerando_qr"] is False
    assert "Gerar QR Code" in resposta.content.decode()


@pytest.mark.django_db
def test_marca_antiga_da_sessao_nao_gera_qr_sozinha(auth_client, monkeypatch, relogio):
    """A sessão guardava só True, ligado para sempre: abrir a página já pedia QR."""
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    sessao = auth_client.session
    sessao["conexoes_whatsapp_gerar_qr"] = True
    sessao.save()
    assert auth_client.get(reverse("pagamentos:conexoes")).context["quer_qr"] is False


@pytest.mark.django_db
def test_pedido_de_qr_vale_so_por_alguns_minutos(auth_client, monkeypatch, relogio):
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    assert auth_client.get(reverse("pagamentos:conexoes")).context["quer_qr"] is True
    relogio[0] += 121
    cache.clear()
    assert auth_client.get(reverse("pagamentos:conexoes")).context["quer_qr"] is False


@pytest.mark.django_db
def test_endpoint_do_qr_gera_guarda_e_reaproveita(auth_client, qr_pedido, relogio):
    url = reverse("pagamentos:conexoes_qr")
    assert auth_client.post(url).json() == {"ok": True}  # ainda válido: não pede outro
    assert len(qr_pedido) == 1
    relogio[0] += 26
    assert auth_client.post(url).json() == {"ok": True}  # expirou: pede um novo
    assert len(qr_pedido) == 2


@pytest.mark.django_db
def test_endpoint_do_qr_exige_login_e_pedido(auth_client, monkeypatch, relogio):
    from django.test import Client

    url = reverse("pagamentos:conexoes_qr")
    assert Client().post(url).status_code == 302
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    resposta = auth_client.post(url)  # sem ter clicado em "Gerar QR Code"
    assert resposta.status_code == 409 and resposta.json()["ok"] is False


@pytest.mark.django_db
def test_endpoint_do_qr_devolve_o_erro_da_evolution(auth_client, monkeypatch, relogio):
    def _falha():
        raise WhatsAppErro("Falha de comunicação com a Evolution API.")

    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_qrcode", _falha)
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    dados = auth_client.post(reverse("pagamentos:conexoes_qr")).json()
    assert dados == {"ok": False, "erro": "Falha de comunicação com a Evolution API."}


@pytest.mark.django_db
def test_endpoint_do_qr_nao_pede_nada_quando_ja_conectou(auth_client, monkeypatch, relogio):
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    cache.clear()
    chamadas = []
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "open")
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_qrcode", lambda: chamadas.append(1) or "data:x")
    assert auth_client.post(reverse("pagamentos:conexoes_qr")).json() == {"ok": True, "conectado": True}
    assert chamadas == []


@pytest.mark.django_db
def test_voltar_a_pagina_antes_de_expirar_reaproveita_o_qr_e_retoma_o_cronometro(
    auth_client, qr_pedido, relogio
):
    url = reverse("pagamentos:conexoes")
    primeira = auth_client.get(url)
    assert primeira.context["qr_code"].endswith("QR1")
    assert primeira.context["qr_atraso_css"] == "-0.0s"

    relogio[0] += 10  # saiu da página e voltou 10 s depois
    segunda = auth_client.get(url)
    assert segunda.context["qr_code"].endswith("QR1")  # mesmo código, sem pedir outro
    assert segunda.context["qr_atraso_css"] == "-10.0s"  # barra retoma de onde parou
    assert segunda.context["qr_restante_segundos"] == 15
    assert len(qr_pedido) == 1


@pytest.mark.django_db
def test_qr_expirado_nao_e_reaproveitado(auth_client, qr_pedido, relogio):
    url = reverse("pagamentos:conexoes")
    relogio[0] += 26  # passou dos 25 s
    resposta = auth_client.get(url)
    assert resposta.context["qr_code"] == "" and resposta.context["gerando_qr"] is True  # pede outro em segundo plano
    auth_client.post(reverse("pagamentos:conexoes_qr"))
    resposta = auth_client.get(url)
    assert resposta.context["qr_code"].endswith("QR2")
    assert resposta.context["qr_atraso_css"] == "-0.0s"
    assert len(qr_pedido) == 2


@pytest.mark.django_db
def test_gerar_outro_qr_descarta_o_guardado(auth_client, qr_pedido):
    url = reverse("pagamentos:conexoes")
    auth_client.get(url)
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    assert auth_client.get(url).context["qr_code"] == ""  # o código antigo saiu
    auth_client.post(reverse("pagamentos:conexoes_qr"))
    assert auth_client.get(url).context["qr_code"].endswith("QR2")


@pytest.mark.django_db
def test_qr_continua_contando_em_outra_sessao(auth_client, qr_pedido, django_user_model, relogio):
    """O QR é da instância da Evolution: outra sessão (ou o mesmo usuário depois de
    sair e entrar) vê o mesmo código com a contagem de onde está, não de 25 s."""
    url = reverse("pagamentos:conexoes")
    relogio[0] += 12
    auth_client.logout()
    auth_client.force_login(django_user_model.objects.get(username="op"))
    sessao = auth_client.session
    sessao["conexoes_whatsapp_gerar_qr"] = (BASE + datetime.timedelta(seconds=relogio[0] - 12)).timestamp()
    sessao.save()
    resposta = auth_client.get(url)
    assert resposta.context["qr_code"].endswith("QR1")  # não pediu outro
    assert resposta.context["qr_atraso_css"] == "-12.0s"
    assert len(qr_pedido) == 1
