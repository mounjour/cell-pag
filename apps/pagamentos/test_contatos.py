"""Contatos de cobrança e promessas de pagamento."""

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import contatos
from apps.pagamentos.agenda import montar_agenda_do_dia
from apps.pagamentos.forms import ContatoDeCobrancaForm
from apps.pagamentos.models import ContatoDeCobranca, Pagamento

pytestmark = pytest.mark.django_db

HOJE = timezone.localdate


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def _atrasado(cliente, dias=3):
    return novo_contrato(
        cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00",
        proximo_vencimento=HOJE() - datetime.timedelta(days=dias),
    )


def _promessa(contrato, dias_a_frente=2, criado_ha_dias=0, **extra):
    contato = ContatoDeCobranca.objects.create(
        contrato=contrato, resultado=ContatoDeCobranca.Resultado.PROMESSA,
        promessa_para=HOJE() + datetime.timedelta(days=dias_a_frente), **extra,
    )
    if criado_ha_dias:
        ContatoDeCobranca.objects.filter(pk=contato.pk).update(
            criado_em=timezone.now() - datetime.timedelta(days=criado_ha_dias))
        contato.refresh_from_db()
    return contato


# ── formulário ─────────────────────────────────────────────────────────────

def test_promessa_exige_a_data():
    form = ContatoDeCobrancaForm({"tipo": "ligacao", "resultado": "promessa", "promessa_para": "", "nota": ""})
    assert not form.is_valid() and "até quando" in str(form.errors["promessa_para"])


def test_promessa_no_passado_e_recusada():
    ontem = (HOJE() - datetime.timedelta(days=1)).isoformat()
    form = ContatoDeCobrancaForm({"tipo": "ligacao", "resultado": "promessa", "promessa_para": ontem})
    assert not form.is_valid() and "passado" in str(form.errors["promessa_para"])


def test_resultado_outro_exige_anotacao_e_descarta_a_data():
    vazio = ContatoDeCobrancaForm({"tipo": "whatsapp", "resultado": "outro", "nota": " "})
    assert not vazio.is_valid() and "nota" in vazio.errors
    form = ContatoDeCobrancaForm({"tipo": "whatsapp", "resultado": "sem_resposta", "promessa_para": "2030-01-01"})
    assert form.is_valid() and form.cleaned_data["promessa_para"] is None


# ── criar e apagar ─────────────────────────────────────────────────────────

def test_anotar_promessa_pela_tela(auth_client, cliente):
    ct = _atrasado(cliente)
    data = (HOJE() + datetime.timedelta(days=3)).isoformat()
    resposta = auth_client.post(reverse("pagamentos:contato_novo", args=[ct.pk]), {
        "tipo": "ligacao", "resultado": "promessa", "promessa_para": data, "nota": "Paga na sexta"})
    assert resposta.status_code == 302 and resposta.url.endswith("#contatos")
    contato = ContatoDeCobranca.objects.get()
    assert contato.contrato == ct and contato.autor and contato.nota == "Paga na sexta"
    assert contato.promessa_para.isoformat() == data


def test_erro_no_formulario_nao_grava(auth_client, cliente):
    ct = _atrasado(cliente)
    auth_client.post(reverse("pagamentos:contato_novo", args=[ct.pk]), {"tipo": "ligacao", "resultado": "promessa"})
    assert not ContatoDeCobranca.objects.exists()


def test_apagar_anotacao(auth_client, cliente):
    ct = _atrasado(cliente)
    contato = _promessa(ct)
    auth_client.post(reverse("pagamentos:contato_excluir", args=[contato.pk]))
    assert not ContatoDeCobranca.objects.exists()


def test_acoes_exigem_login(cliente):
    ct = _atrasado(cliente)
    anonimo = Client()
    assert anonimo.post(reverse("pagamentos:contato_novo", args=[ct.pk]), {}).status_code == 302
    assert not ContatoDeCobranca.objects.exists()


# ── estado da promessa ─────────────────────────────────────────────────────

def test_estados_da_promessa(cliente):
    ct = _atrasado(cliente)
    contato = _promessa(ct, dias_a_frente=2)
    assert contatos.promessas_em_aberto()[ct.pk].estado == contatos.PENDENTE
    ContatoDeCobranca.objects.filter(pk=contato.pk).update(promessa_para=HOJE())
    assert contatos.promessas_em_aberto()[ct.pk].estado == contatos.HOJE
    ContatoDeCobranca.objects.filter(pk=contato.pk).update(promessa_para=HOJE() - datetime.timedelta(days=1))
    assert contatos.promessas_em_aberto()[ct.pk].estado == contatos.QUEBRADA


def test_so_a_promessa_mais_recente_vale(cliente):
    ct = _atrasado(cliente)
    antiga = _promessa(ct, dias_a_frente=-1 + 1, criado_ha_dias=5)  # vence hoje
    ContatoDeCobranca.objects.filter(pk=antiga.pk).update(promessa_para=HOJE() - datetime.timedelta(days=2))
    nova = _promessa(ct, dias_a_frente=4)
    promessa = contatos.promessas_em_aberto()[ct.pk]
    assert promessa.contato.pk == nova.pk and promessa.estado == contatos.PENDENTE


def test_pagamento_depois_da_promessa_a_cumpre(cliente):
    ct = _atrasado(cliente)
    _promessa(ct, dias_a_frente=0, criado_ha_dias=1)
    assert ct.pk in contatos.promessas_em_aberto()
    Pagamento.objects.create(contrato=ct, valor_pago=Decimal("100.00"), data_pagamento=HOJE())
    assert ct.pk not in contatos.promessas_em_aberto()


def test_pagamento_anterior_a_promessa_nao_conta(cliente):
    ct = _atrasado(cliente)
    pagamento = Pagamento.objects.create(contrato=ct, valor_pago=Decimal("100.00"), data_pagamento=HOJE())
    Pagamento.objects.filter(pk=pagamento.pk).update(criado_em=timezone.now() - datetime.timedelta(days=3))
    _promessa(ct, dias_a_frente=0)
    assert ct.pk in contatos.promessas_em_aberto()


def test_contrato_quitado_nao_tem_promessa_em_aberto(cliente):
    ct = _atrasado(cliente)
    _promessa(ct, dias_a_frente=0)
    ct.status = Contrato.Status.QUITADO
    ct.save()
    assert contatos.promessas_em_aberto() == {}


def test_a_retornar_traz_so_hoje_e_vencidas(cliente):
    de_hoje, futura = _atrasado(cliente), _atrasado(cliente)
    _promessa(de_hoje, dias_a_frente=0)
    _promessa(futura, dias_a_frente=5)
    assert [p.contato.contrato.pk for p in contatos.promessas_a_retornar()] == [de_hoje.pk]


# ── telas e avisos ─────────────────────────────────────────────────────────

def test_cobrar_hoje_mostra_a_promessa_na_linha_e_o_card(auth_client, cliente):
    ct = _atrasado(cliente)
    _promessa(ct, dias_a_frente=0, nota="Vai pagar à tarde")
    agenda = montar_agenda_do_dia()
    assert agenda["linhas"][0]["promessa"].estado == contatos.HOJE
    html = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert "Promessas de pagamento" in html and "prometeu pagar hoje" in html and "Vai pagar à tarde" in html
    assert "de pagamento para hoje ou vencida" in html  # toast


def test_promessa_futura_aparece_na_linha_mas_nao_no_card_nem_no_aviso(auth_client, cliente):
    ct = _atrasado(cliente)
    _promessa(ct, dias_a_frente=3)
    html = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert "prometeu pagar" in html and "Promessas de pagamento" not in html


def test_card_de_notificacoes_conta_as_promessas(auth_client, cliente):
    ct = _atrasado(cliente)
    _promessa(ct, dias_a_frente=0)
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert "promessa de pagamento para hoje ou vencida" in html


def test_detalhe_do_contrato_tem_o_formulario_o_historico_e_a_promessa(auth_client, cliente):
    ct = _atrasado(cliente)
    url = reverse("contratos:detalhe", args=[ct.pk])
    html = auth_client.get(url).content.decode()
    assert 'id="contatos"' in html and "Anotar contato" in html and "Nenhum contato anotado" in html

    _promessa(ct, dias_a_frente=3, nota="Cliente viaja")
    html = auth_client.get(url).content.decode()
    assert "promessa em aberto" in html and "Cliente viaja" in html


def test_promessa_quebrada_aparece_no_detalhe(auth_client, cliente):
    ct = _atrasado(cliente)
    contato = _promessa(ct, dias_a_frente=1)
    ContatoDeCobranca.objects.filter(pk=contato.pk).update(promessa_para=HOJE() - datetime.timedelta(days=2))
    html = auth_client.get(reverse("contratos:detalhe", args=[ct.pk])).content.decode()
    assert "promessa não cumprida" in html


def test_ficha_do_cliente_lista_os_contatos(auth_client, cliente):
    ct = _atrasado(cliente)
    _promessa(ct, dias_a_frente=2, nota="Conversou no balcão")
    html = auth_client.get(reverse("clientes:detalhe", args=[cliente.pk])).content.decode()
    assert "Contatos de cobrança" in html and "Conversou no balcão" in html
