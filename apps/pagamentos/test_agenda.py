"""Testes do filtro por tipo de contrato (estrutura) na agenda do dia."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.agenda import montar_agenda_do_dia

date = datetime.date


@pytest.fixture
def cliente(db):
    c = Cliente(nome="Fulano de Tal", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    c.full_clean()
    c.save()
    return c


def _contrato_atrasado(cliente, **kwargs):
    """Contrato diário iniciado há 30 dias — sempre atrasado "hoje", qualquer
    que seja a data real em que os testes rodarem."""
    hoje = timezone.localdate()
    inicio = hoje - datetime.timedelta(days=30)
    dados = dict(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        valor_total=Decimal("400.00"),
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("40.00"),
        num_parcelas=60,
        data_inicio=inicio,
    )
    dados.update(kwargs)
    ct = Contrato.objects.create(**dados)
    ct.gerar_vencimentos(dias_a_frente=60, hoje=hoje)
    return ct


@pytest.mark.django_db
def test_montar_agenda_sem_filtro_traz_todos_os_tipos(cliente):
    _contrato_atrasado(cliente, apelido="A", estrutura=Contrato.Estrutura.DIARIA)
    _contrato_atrasado(cliente, apelido="B", estrutura=Contrato.Estrutura.SEMANAL)
    agenda = montar_agenda_do_dia()
    apelidos = {linha["contrato"].apelido for linha in agenda["linhas"]}
    assert apelidos == {"A", "B"}


@pytest.mark.django_db
def test_montar_agenda_filtra_por_estrutura(cliente):
    _contrato_atrasado(cliente, apelido="A", estrutura=Contrato.Estrutura.DIARIA)
    _contrato_atrasado(cliente, apelido="B", estrutura=Contrato.Estrutura.SEMANAL)
    agenda = montar_agenda_do_dia(estrutura=Contrato.Estrutura.SEMANAL)
    apelidos = {linha["contrato"].apelido for linha in agenda["linhas"]}
    assert apelidos == {"B"}


@pytest.mark.django_db
def test_cobrar_hoje_view_filtra_por_estrutura(auth_client, cliente):
    _contrato_atrasado(cliente, apelido="A", estrutura=Contrato.Estrutura.DIARIA)
    _contrato_atrasado(cliente, apelido="B", estrutura=Contrato.Estrutura.SEMANAL)

    resp = auth_client.get(reverse("pagamentos:cobrar_hoje"), {"estrutura": "semanal"})
    apelidos = {linha["contrato"].apelido for linha in resp.context["linhas"]}
    assert apelidos == {"B"}
    assert resp.context["estrutura_atual"] == "semanal"

    resp_tudo = auth_client.get(reverse("pagamentos:cobrar_hoje"))
    apelidos_tudo = {linha["contrato"].apelido for linha in resp_tudo.context["linhas"]}
    assert apelidos_tudo == {"A", "B"}
