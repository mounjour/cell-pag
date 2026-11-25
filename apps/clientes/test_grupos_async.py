import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.pagamentos import whatsapp

pytestmark = pytest.mark.django_db
GRUPO = "120363012345678901@g.us"


@pytest.fixture(autouse=True)
def limpar_cache():
    cache.clear()
    yield
    cache.clear()


def test_formulario_abre_e_salva_sem_consultar_api(auth_client, monkeypatch):
    def nao_consultar(*args, **kwargs):
        pytest.fail("O formulário não deve aguardar a API")
    monkeypatch.setattr(whatsapp, "grupos_do_whatsapp", nao_consultar)
    html = auth_client.get(reverse("clientes:novo")).content.decode()
    assert "Carregando grupos…" in html and "Tentar novamente" in html
    cache.set("whatsapp_grupos_antigo", [{"id": GRUPO, "nome": "Financeiro", "participantes": 3}])
    resposta = auth_client.post(reverse("clientes:novo"), {
        "nome": "Maria", "cpf": "52998224725", "telefone_whatsapp": "88999990000", "grupo_whatsapp": GRUPO,
    })
    assert resposta.status_code == 302
    cliente = Cliente.objects.get()
    assert cliente.grupo_whatsapp == GRUPO and cliente.grupo_whatsapp_nome == "Financeiro"
    cache.clear()
    resposta = auth_client.post(reverse("clientes:editar", args=[cliente.pk]), {
        "nome": "Maria", "cpf": cliente.cpf, "telefone_whatsapp": "88999990000", "grupo_whatsapp": GRUPO,
    })
    assert resposta.status_code == 302
    cliente.refresh_from_db()
    assert cliente.grupo_whatsapp_nome == "Financeiro"


def test_endpoint_aguarda_api_e_reutiliza_cache(auth_client, settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    chamadas = []
    def consultar(caminho, consulta, timeout):
        chamadas.append(timeout)
        return [{"id": GRUPO, "subject": "Financeiro", "size": 3}]
    monkeypatch.setattr(whatsapp, "_chamar_evolution_get", consultar)
    for _ in range(2):
        resposta = auth_client.get(reverse("clientes:grupos_whatsapp"))
        assert resposta.status_code == 200
        assert resposta.json()["grupos"][0]["id"] == GRUPO
    assert chamadas == [45]
    token = resposta.json()["grupos"][0]["token"]
    cache.clear()  # O POST pode chegar em outro worker, sem o cache da consulta.
    resposta = auth_client.post(reverse("clientes:novo"), {
        "nome": "Maria", "cpf": "52998224725", "telefone_whatsapp": "88999990000",
        "grupo_whatsapp": GRUPO, "grupo_whatsapp_token": token,
    })
    assert resposta.status_code == 302
    assert Cliente.objects.get().grupo_whatsapp_nome == "Financeiro"


def test_falha_permite_nova_tentativa(auth_client, monkeypatch):
    def falha(**kwargs):
        raise whatsapp.WhatsAppErro("timeout")
    monkeypatch.setattr(whatsapp, "consultar_grupos", falha)
    assert auth_client.get(reverse("clientes:grupos_whatsapp")).status_code == 503
    monkeypatch.setattr(whatsapp, "consultar_grupos", lambda **kw: {"grupos": []})
    assert auth_client.get(reverse("clientes:grupos_whatsapp")).json() == {"grupos": []}


def test_endpoint_exige_login(client):
    assert client.get(reverse("clientes:grupos_whatsapp")).status_code == 302
