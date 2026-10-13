"""Controle de bloqueio de aparelhos por atraso."""

import datetime

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.aparelhos import bloqueios
from apps.aparelhos.models import BloqueioAparelho
from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos.agenda import montar_agenda_do_dia

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def _atrasado(cliente, dias=10, **extra):
    """Contrato mensal com a parcela vencida há ``dias`` dias (data manual, sem parcelas geradas)."""
    return novo_contrato(
        cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00",
        proximo_vencimento=timezone.localdate() - datetime.timedelta(days=dias), **extra,
    )


def _em_dia(cliente):
    return novo_contrato(
        cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00",
        proximo_vencimento=timezone.localdate() + datetime.timedelta(days=10),
    )


def test_atraso_de_7_dias_entra_em_para_bloquear(cliente):
    ct = _atrasado(cliente, dias=7)
    painel = bloqueios.montar_painel()
    assert [l["contrato"].pk for l in painel["a_bloquear"]] == [ct.pk]


def test_atraso_menor_que_7_dias_nao_entra(cliente):
    _atrasado(cliente, dias=6)
    assert bloqueios.montar_painel()["a_bloquear"] == []


def test_registrar_bloqueio_tira_da_fila_e_marca_a_linha_da_agenda(auth_client, cliente):
    ct = _atrasado(cliente)
    assert montar_agenda_do_dia()["n_bloqueio"] == 1
    resposta = auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]), {"observacao": "iCloud"})
    assert resposta.status_code == 302
    bloqueio = BloqueioAparelho.objects.get()
    assert bloqueio.contrato == ct and bloqueio.observacao == "iCloud" and bloqueio.bloqueado_por and bloqueio.ativo

    agenda = montar_agenda_do_dia()
    assert agenda["n_bloqueio"] == 0
    assert agenda["linhas"][0]["bloqueado"] is True
    painel = bloqueios.montar_painel()
    assert painel["a_bloquear"] == [] and [i["bloqueio"].pk for i in painel["bloqueados"]] == [bloqueio.pk]


def test_nao_duplica_bloqueio_ativo(auth_client, cliente):
    ct = _atrasado(cliente)
    url = reverse("aparelhos:bloquear", args=[ct.pk])
    auth_client.post(url)
    auth_client.post(url)
    assert BloqueioAparelho.objects.count() == 1


def test_contrato_quitado_nao_pode_ser_bloqueado(auth_client, cliente):
    ct = _atrasado(cliente)
    ct.status = Contrato.Status.QUITADO
    ct.save()
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    assert not BloqueioAparelho.objects.exists()


def test_cliente_que_regularizou_vai_para_desbloquear(auth_client, cliente):
    ct = _atrasado(cliente)
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    assert bloqueios.contar_a_desbloquear() == 0  # ainda deve

    ct.proximo_vencimento = timezone.localdate() + datetime.timedelta(days=15)  # pagou: próxima parcela no futuro
    ct.save()
    cache.clear()
    painel = bloqueios.montar_painel()
    assert len(painel["para_desbloquear"]) == 1 and painel["bloqueados"] == []
    assert bloqueios.contar_a_desbloquear() == 1


def test_contrato_quitado_com_bloqueio_vai_para_desbloquear(auth_client, cliente):
    ct = _atrasado(cliente)
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    ct.status = Contrato.Status.QUITADO
    ct.save()
    item = bloqueios.montar_painel()["para_desbloquear"][0]
    assert item["quitado"] is True


def test_desbloquear_registra_quem_e_quando_e_vai_para_o_historico(auth_client, cliente):
    ct = _atrasado(cliente)
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    bloqueio = BloqueioAparelho.objects.get()
    resposta = auth_client.post(reverse("aparelhos:desbloquear", args=[bloqueio.pk]))
    assert resposta.status_code == 302
    bloqueio.refresh_from_db()
    assert not bloqueio.ativo and bloqueio.desbloqueado_por is not None
    painel = bloqueios.montar_painel()
    assert [b.pk for b in painel["historico"]] == [bloqueio.pk]
    # pode bloquear de novo depois de liberar
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    assert BloqueioAparelho.objects.count() == 2


def test_so_um_bloqueio_ativo_por_contrato_no_banco(cliente):
    from django.db import IntegrityError, transaction

    ct = _atrasado(cliente)
    BloqueioAparelho.objects.create(contrato=ct)
    with pytest.raises(IntegrityError), transaction.atomic():
        BloqueioAparelho.objects.create(contrato=ct)


def test_acoes_exigem_login(cliente):
    ct = _atrasado(cliente)
    anonimo = Client()
    assert anonimo.get(reverse("aparelhos:bloqueios")).status_code == 302
    assert anonimo.post(reverse("aparelhos:bloquear", args=[ct.pk])).status_code == 302
    assert not BloqueioAparelho.objects.exists()


def test_redirecionamento_ignora_endereco_de_fora(auth_client, cliente):
    ct = _atrasado(cliente)
    resposta = auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]), {"next": "https://exemplo.com/x"})
    assert resposta.status_code == 302 and resposta.url == reverse("aparelhos:bloqueios")
    resposta = auth_client.post(reverse("aparelhos:desbloquear", args=[BloqueioAparelho.objects.get().pk]),
                                {"next": reverse("contratos:detalhe", args=[ct.pk])})
    assert resposta.url == reverse("contratos:detalhe", args=[ct.pk])


def test_pagina_de_bloqueios_mostra_as_filas_e_avisa_como_notificacao(auth_client, cliente):
    ct = _atrasado(cliente)
    resposta = auth_client.get(reverse("aparelhos:bloqueios"))
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert "Para bloquear" in html and ct.apelido in html and "Bloqueei" in html
    assert "esperam bloqueio" in html or "espera bloqueio" in html  # toast da página


def test_menu_e_card_de_notificacoes_apontam_para_a_tela_de_bloqueios(auth_client, cliente):
    _atrasado(cliente)
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert reverse("aparelhos:bloqueios") in html
    assert "para bloquear" in html  # item no card de notificações


def test_contagem_do_card_inclui_os_aparelhos_a_desbloquear(auth_client, cliente):
    ct = _atrasado(cliente)
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    ct.proximo_vencimento = timezone.localdate() + datetime.timedelta(days=20)
    ct.save()
    cache.clear()
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert "para desbloquear" in html and "cliente regularizou" in html


def test_detalhe_do_contrato_oferece_bloquear_e_depois_desbloquear(auth_client, cliente):
    ct = _atrasado(cliente)
    url = reverse("contratos:detalhe", args=[ct.pk])
    html = auth_client.get(url).content.decode()
    assert reverse("aparelhos:bloquear", args=[ct.pk]) in html and "Marcar como bloqueado" in html

    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]), {"observacao": "MDM", "next": url})
    html = auth_client.get(url).content.decode()
    assert "Aparelho bloqueado" in html and "Marcar como desbloqueado" in html and "MDM" in html
    assert "hora de bloquear o aparelho" not in html  # o aviso some depois de registrado


def test_cobrar_hoje_mostra_bloqueado_em_vez_de_pedir_bloqueio(auth_client, cliente):
    ct = _atrasado(cliente)
    antes = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert "bloquear aparelho" in antes
    auth_client.post(reverse("aparelhos:bloquear", args=[ct.pk]))
    cache.clear()
    depois = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert "bloquear aparelho" not in depois and "bloqueado" in depois
