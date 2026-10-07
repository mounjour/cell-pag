"""Lista de clientes: situação de cobrança, filtros rápidos e contatos."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.clientes.situacao import EM_ATRASO, EM_DIA, SEM_CONTRATO, situacoes_dos_clientes
from apps.contratos.models import Contrato
from apps.pagamentos.models import Vencimento

HOJE = datetime.date(2026, 10, 6)


def novo_cliente(nome, telefone="+5583999990000"):
    c = Cliente(nome=nome, cpf=CPFGen().generate(), telefone_whatsapp=telefone)
    c.full_clean()
    c.save()
    return c


def contrato_com_parcela(cliente, vence, valor="100.00", **extra):
    ct = Contrato.objects.create(
        cliente=cliente, apelido="iPhone", aparelho_modelo="iPhone 11", imei="359999053372501",
        valor_total=Decimal("1200.00"), estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal(valor), num_parcelas=12, data_inicio=datetime.date(2026, 1, 1), **extra,
    )
    Vencimento.objects.create(contrato=ct, numero=1, data_vencimento=vence, valor_previsto=Decimal(valor))
    return ct


@pytest.mark.django_db
def test_situacao_atrasado_em_dia_e_sem_contrato():
    atrasado = novo_cliente("Atrasado")
    contrato_com_parcela(atrasado, HOJE - datetime.timedelta(days=5))
    em_dia = novo_cliente("Em Dia")
    contrato_com_parcela(em_dia, HOJE + datetime.timedelta(days=10), valor="250.00")
    vazio = novo_cliente("Sem Contrato")

    s = situacoes_dos_clientes([atrasado.pk, em_dia.pk, vazio.pk], hoje=HOJE)

    a = s[atrasado.pk]
    assert (a.estado, a.dias_atraso) == (EM_ATRASO, 5)
    assert a.juros == Decimal("25.00") and a.devido == Decimal("125.00")  # R$ 5 por dia
    d = s[em_dia.pk]
    assert d.estado == EM_DIA and d.proximo_vencimento == HOJE + datetime.timedelta(days=10)
    assert d.proximo_valor == Decimal("250.00") and d.devido == Decimal("0.00")
    assert s[vazio.pk].estado == SEM_CONTRATO


@pytest.mark.django_db
def test_vence_hoje_nao_e_atraso_e_cai_em_dia_no_filtro():
    c = novo_cliente("Vence Hoje")
    contrato_com_parcela(c, HOJE)
    sit = situacoes_dos_clientes([c.pk], hoje=HOJE)[c.pk]
    assert sit.estado == "hoje" and sit.dias_atraso == 0 and sit.filtro == EM_DIA


@pytest.mark.django_db
def test_contrato_quitado_nao_conta_como_devedor():
    c = novo_cliente("Quitado")
    contrato_com_parcela(c, HOJE - datetime.timedelta(days=30), status=Contrato.Status.QUITADO)
    assert situacoes_dos_clientes([c.pk], hoje=HOJE)[c.pk].estado == "quitado"


@pytest.mark.django_db
def test_lista_mostra_situacao_valor_e_contatos(auth_client):
    c = novo_cliente("Maria Atrasada")
    contrato_com_parcela(c, datetime.date.today() - datetime.timedelta(days=2))
    html = auth_client.get(reverse("clientes:lista")).content.decode()
    assert "Maria Atrasada" in html and "Atrasado · 2 dias" in html
    assert "R$ 110,00" in html  # 100 + 2 dias × R$ 5
    assert f"tel:{c.telefone_whatsapp.as_e164}" in html and "wa.me" in html


@pytest.mark.django_db
def test_filtros_rapidos_e_contagens(auth_client):
    atrasado = novo_cliente("Atrasado Um")
    contrato_com_parcela(atrasado, datetime.date.today() - datetime.timedelta(days=2))
    novo_cliente("Sem Contrato Um")

    resp = auth_client.get(reverse("clientes:lista"), {"situacao": "atraso"})
    assert [c.nome for c in resp.context["clientes"]] == ["Atrasado Um"]
    assert resp.context["contagens"]["todos"] == 2
    assert resp.context["contagens"]["atraso"] == 1 and resp.context["contagens"]["sem_contrato"] == 1

    resp = auth_client.get(reverse("clientes:lista"), {"situacao": "sem_contrato"})
    assert [c.nome for c in resp.context["clientes"]] == ["Sem Contrato Um"]

    resp = auth_client.get(reverse("clientes:lista"), {"situacao": "invalido"})
    assert resp.context["filtro_atual"] == "" and len(resp.context["clientes"]) == 2


@pytest.mark.django_db
def test_busca_continua_funcionando_junto_com_o_filtro(auth_client):
    a = novo_cliente("Ana Atrasada")
    b = novo_cliente("Bruno Atrasado")
    for c in (a, b):
        contrato_com_parcela(c, datetime.date.today() - datetime.timedelta(days=3))
    resp = auth_client.get(reverse("clientes:lista"), {"q": "Bruno", "situacao": "atraso"})
    assert [c.nome for c in resp.context["clientes"]] == ["Bruno Atrasado"]


@pytest.mark.django_db
def test_a_partir_de_tres_dias_aparece_inadimplente(auth_client):
    c = novo_cliente("Muito Atrasada")
    contrato_com_parcela(c, datetime.date.today() - datetime.timedelta(days=4))
    assert "Inadimplente · 4 dias" in auth_client.get(reverse("clientes:lista")).content.decode()


# ── Aviso de bloquear o aparelho a partir de 7 dias de atraso ──

@pytest.mark.django_db
@pytest.mark.parametrize("dias, avisa", [(6, False), (7, True), (10, True)])
def test_lista_avisa_bloquear_aparelho_a_partir_de_7_dias(auth_client, dias, avisa):
    c = novo_cliente(f"Atraso {dias}")
    contrato_com_parcela(c, datetime.date.today() - datetime.timedelta(days=dias))
    html = auth_client.get(reverse("clientes:lista")).content.decode()
    assert ("bloquear aparelho" in html) is avisa


@pytest.mark.django_db
def test_card_de_notificacoes_conta_os_aparelhos_a_bloquear(auth_client):
    from django.core.cache import cache

    cache.clear()
    for nome, dias in (("Seis", 6), ("Sete", 7), ("Dez", 10)):
        contrato_com_parcela(novo_cliente(nome), datetime.date.today() - datetime.timedelta(days=dias))
    cache.clear()
    html = auth_client.get(reverse("clientes:lista")).content.decode()
    assert "2 aparelhos para bloquear (7+ dias de atraso)" in html


@pytest.mark.django_db
def test_card_de_notificacoes_no_singular_e_sem_aviso_quando_nao_ha(auth_client):
    from django.core.cache import cache

    cache.clear()
    assert "para bloquear" not in auth_client.get(reverse("clientes:lista")).content.decode()
    contrato_com_parcela(novo_cliente("Um So"), datetime.date.today() - datetime.timedelta(days=9))
    cache.clear()
    assert "1 aparelho para bloquear (7+ dias de atraso)" in auth_client.get(reverse("clientes:lista")).content.decode()
