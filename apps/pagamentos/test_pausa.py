"""Começar, pausar e retomar as cobranças automáticas (chave geral)."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.pagamentos.cobranca import processar_cobrancas
from apps.pagamentos.models import Cobranca, ConfiguracaoCobranca

URL = "pagamentos:cobrancas_pausa"
AVISO = "Cobranças automáticas desligadas"


@pytest.fixture
def exige_inicio(settings):
    settings.COBRANCAS_EXIGEM_INICIO = True


@pytest.mark.django_db
def test_em_producao_nascem_paradas(exige_inicio):
    assert ConfiguracaoCobranca.esta_pausada() is True
    assert ConfiguracaoCobranca.obter().nunca_iniciada


@pytest.mark.django_db
def test_comecar_exige_conferencia(exige_inicio, auth_client):
    auth_client.post(reverse(URL), {"acao": "comecar"})
    assert ConfiguracaoCobranca.esta_pausada() is True

    auth_client.post(reverse(URL), {"acao": "comecar", "conferido": "1"})
    config = ConfiguracaoCobranca.obter()
    assert not config.pausada and config.iniciada_em and not config.nunca_iniciada


@pytest.mark.django_db
def test_pausar_e_retomar_nao_pedem_conferencia_de_novo(exige_inicio, auth_client):
    auth_client.post(reverse(URL), {"acao": "comecar", "conferido": "1"})
    auth_client.post(reverse(URL), {"acao": "pausar"})
    config = ConfiguracaoCobranca.obter()
    assert config.pausada and config.pausada_em and config.pausada_por

    auth_client.post(reverse(URL), {"acao": "retomar"})
    config.refresh_from_db()
    assert not config.pausada and config.pausada_em is None and config.pausada_por is None


@pytest.mark.django_db
def test_acoes_exigem_login(client, exige_inicio):
    resp = client.post(reverse(URL), {"acao": "comecar", "conferido": "1"})
    assert resp.status_code == 302 and "/entrar/" in resp["Location"]
    assert ConfiguracaoCobranca.esta_pausada() is True


@pytest.mark.django_db
def test_tela_mostra_o_botao_certo_em_cada_estado(exige_inicio, auth_client):
    pagina = lambda: auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert "Começar cobranças" in pagina()
    ConfiguracaoCobranca.definir(False)
    assert "Pausar cobranças automáticas" in pagina()
    ConfiguracaoCobranca.definir(True)
    assert "Retomar cobranças automáticas" in pagina()


@pytest.mark.django_db
def test_aviso_aparece_no_card_de_notificacoes_enquanto_desligadas(exige_inicio, auth_client):
    assert AVISO in auth_client.get(reverse("clientes:lista")).content.decode()
    ConfiguracaoCobranca.definir(False)
    assert AVISO not in auth_client.get(reverse("clientes:lista")).content.decode()


@pytest.mark.django_db
def test_rotina_nao_cobra_nem_gera_nada_enquanto_desligada(exige_inicio):
    resultado = processar_cobrancas()
    assert resultado["pausada"] is True
    assert resultado["enviadas"] == resultado["preparadas"] == resultado["erros"] == 0
    assert not Cobranca.objects.exists()


@pytest.mark.django_db
def test_comando_avisa_que_esta_desligado_e_nao_falha(exige_inicio):
    saida = StringIO()
    call_command("enviar_cobrancas_clientes", stdout=saida)
    assert "PAUSADAS" in saida.getvalue()
