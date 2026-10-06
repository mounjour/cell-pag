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
def qr_pedido(auth_client, monkeypatch):
    """Cliente logado, WhatsApp desconectado e QR já pedido; devolve a lista de chamadas."""
    chamadas = []

    def _qr():
        chamadas.append(1)
        return f"data:image/png;base64,QR{len(chamadas)}"

    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "close")
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_qrcode", _qr)
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    return chamadas


@pytest.mark.django_db
def test_voltar_a_pagina_antes_de_expirar_reaproveita_o_qr_e_retoma_o_cronometro(
    auth_client, qr_pedido, monkeypatch
):
    agora = [1000.0]
    monkeypatch.setattr("apps.pagamentos.views._agora", lambda: BASE + datetime.timedelta(seconds=agora[0]))
    url = reverse("pagamentos:conexoes")

    primeira = auth_client.get(url)
    assert primeira.context["qr_code"].endswith("QR1")
    assert primeira.context["qr_atraso_css"] == "-0.0s"

    agora[0] += 10  # saiu da página e voltou 10 s depois
    segunda = auth_client.get(url)
    assert segunda.context["qr_code"].endswith("QR1")  # mesmo código, sem pedir outro
    assert segunda.context["qr_atraso_css"] == "-10.0s"  # barra retoma de onde parou
    assert segunda.context["qr_restante_segundos"] == 15
    assert len(qr_pedido) == 1


@pytest.mark.django_db
def test_qr_expirado_nao_e_reaproveitado(auth_client, qr_pedido, monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr("apps.pagamentos.views._agora", lambda: BASE + datetime.timedelta(seconds=agora[0]))
    url = reverse("pagamentos:conexoes")
    auth_client.get(url)

    agora[0] += 26  # passou dos 25 s
    resposta = auth_client.get(url)
    assert resposta.context["qr_code"].endswith("QR2")
    assert resposta.context["qr_atraso_css"] == "-0.0s"
    assert len(qr_pedido) == 2


@pytest.mark.django_db
def test_gerar_outro_qr_descarta_o_guardado(auth_client, qr_pedido):
    url = reverse("pagamentos:conexoes")
    auth_client.get(url)
    auth_client.post(reverse("pagamentos:conexoes_gerar_qr"))
    resposta = auth_client.get(url)
    assert resposta.context["qr_code"].endswith("QR2")


@pytest.mark.django_db
def test_qr_continua_contando_em_outra_sessao(auth_client, qr_pedido, django_user_model, monkeypatch):
    """O QR é da instância da Evolution: outra sessão (ou o mesmo usuário depois de
    sair e entrar) vê o mesmo código com a contagem de onde está, não de 25 s."""
    from django.test import Client

    agora = [1000.0]
    monkeypatch.setattr("apps.pagamentos.views._agora", lambda: BASE + datetime.timedelta(seconds=agora[0]))
    url = reverse("pagamentos:conexoes")
    auth_client.get(url)  # primeira sessão pede o QR

    outro = Client()  # outro navegador/aparelho, já com o QR ativo na sessão
    outro.force_login(django_user_model.objects.create_user("outro"))
    outro.post(reverse("pagamentos:conexoes_gerar_qr"))
    # "gerar" descarta o guardado: precisa de código novo
    assert outro.get(url).context["qr_code"].endswith("QR2")

    agora[0] += 12
    auth_client.logout()
    auth_client.force_login(django_user_model.objects.get(username="op"))
    sessao = auth_client.session
    sessao["conexoes_whatsapp_gerar_qr"] = True
    sessao.save()
    resposta = auth_client.get(url)
    assert resposta.context["qr_code"].endswith("QR2")  # não pediu outro
    assert resposta.context["qr_atraso_css"] == "-12.0s"
    assert len(qr_pedido) == 2
