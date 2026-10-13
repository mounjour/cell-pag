"""Contrato cadastrado à mão tira da lista a pendência de importação correspondente."""

import pytest
from django.urls import reverse

from apps.contratos.models import Contrato, ImportacaoContratoPendente
from apps.contratos.test_confirmacao import cadastro, confirmar  # noqa: F401  (cadastro é fixture)

pytestmark = pytest.mark.django_db


def _pendencia(linha=7, **dados):
    base = {"linha": linha, "cliente": "Maria Teste", "modelo": "iPhone 13 128GB", "imei": "", "cpf": ""}
    base.update(dados)
    return ImportacaoContratoPendente.objects.create(dados=base, problemas=["IMEI ausente."], linha_origem=linha)


def _cadastrar(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    return confirmar(auth_client, resumo)


def _abertas():
    return ImportacaoContratoPendente.objects.filter(resolvida_em__isnull=True).count()


def test_mesmo_imei_resolve_a_pendencia(auth_client, cadastro):
    pendencia = _pendencia(imei="359999053372501", cliente="Outro Nome", modelo="outro")
    outra = _pendencia(linha=8, imei="111111111111111")
    assert _cadastrar(auth_client, cadastro).status_code == 302
    pendencia.refresh_from_db(); outra.refresh_from_db()
    assert pendencia.resolvida_em is not None
    assert outra.resolvida_em is None  # outro aparelho: continua pendente


def test_imei_com_pontuacao_tambem_casa(auth_client, cadastro):
    pendencia = _pendencia(imei="35999-9053372501")
    _cadastrar(auth_client, cadastro)
    pendencia.refresh_from_db()
    assert pendencia.resolvida_em is not None


def test_sem_imei_na_planilha_casa_por_cliente_e_modelo(auth_client, cadastro):
    pendencia = _pendencia(cliente="  MARIA   teste ", modelo="iphone 13 128gb")
    _cadastrar(auth_client, cadastro)
    pendencia.refresh_from_db()
    assert pendencia.resolvida_em is not None


def test_cliente_ou_modelo_diferente_nao_resolve(auth_client, cadastro):
    outro_cliente = _pendencia(cliente="Joana")
    outro_modelo = _pendencia(linha=9, modelo="iPhone 11")
    _cadastrar(auth_client, cadastro)
    assert _abertas() == 2
    outro_cliente.refresh_from_db(); outro_modelo.refresh_from_db()
    assert outro_cliente.resolvida_em is None and outro_modelo.resolvida_em is None


def test_na_duvida_nao_resolve(auth_client, cadastro):
    """Duas linhas iguais, sem IMEI: não dá para saber qual é; nenhuma é tocada."""
    _pendencia(linha=7)
    _pendencia(linha=8)
    _cadastrar(auth_client, cadastro)
    assert _abertas() == 2


def test_cpf_da_planilha_vale_mais_que_o_nome(auth_client, cadastro):
    from apps.clientes.models import Cliente

    cliente = Cliente.objects.get(pk=cadastro["cliente"])
    pendencia = _pendencia(cliente="Nome Escrito Diferente", cpf=cliente.cpf)
    _cadastrar(auth_client, cadastro)
    pendencia.refresh_from_db()
    assert pendencia.resolvida_em is not None


def test_pendencia_ja_resolvida_nao_e_mexida(auth_client, cadastro):
    from django.utils import timezone

    antiga = timezone.now() - timezone.timedelta(days=3)
    pendencia = _pendencia(imei="359999053372501")
    ImportacaoContratoPendente.objects.filter(pk=pendencia.pk).update(resolvida_em=antiga)
    _cadastrar(auth_client, cadastro)
    pendencia.refresh_from_db()
    assert pendencia.resolvida_em == antiga


def test_aviso_na_tela_e_pendencia_some_da_lista(auth_client, cadastro):
    _pendencia(linha=12, imei="359999053372501")
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    resposta = auth_client.post(reverse("contratos:novo"), {
        "revisao": resumo.context["revisao"], "acao": "confirmar", "conferido": "1"}, follow=True)
    html = resposta.content.decode()
    assert "Pendência de importação resolvida" in html and "linha 12" in html  # toast
    assert Contrato.objects.count() == 1
    lista = auth_client.get(reverse("contratos:importacao_pendencias")).content.decode()
    assert "Nenhuma pendência aberta" in lista


def test_sem_pendencias_nada_muda(auth_client, cadastro):
    resposta = _cadastrar(auth_client, cadastro)
    assert resposta.status_code == 302 and Contrato.objects.count() == 1
