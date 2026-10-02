import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.pagamentos.whatsapp import WhatsAppErro


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
