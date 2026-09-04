"""Testes do lembrete diário no WhatsApp da Yslane (Fase 2, Modalidade A).

O envio (`lembrete.enviar`) é um stub — sem conta WhatsApp Business ainda
(Alisson, 04/09) — então os testes cobrem o texto montado e o "envio"
(log + retorno), não uma chamada de API de verdade.
"""

import datetime
import logging
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos import lembrete
from apps.pagamentos.agenda import montar_agenda_do_dia

date = datetime.date
timedelta = datetime.timedelta


@pytest.fixture
def cliente(db):
    c = Cliente(nome="Fulano de Tal", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    c.full_clean()
    c.save()
    return c


def _contrato(cliente, **kwargs):
    dados = dict(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        valor_total=Decimal("2400.00"),
        estrutura=Contrato.Estrutura.DIARIA,
        data_inicio=date(2026, 2, 20),
    )
    dados.update(kwargs)
    return Contrato.objects.create(**dados)


# ── montar_texto ──────────────────────────────────────────────────────────

def test_texto_sem_ninguem_pra_cobrar():
    agenda = {"hoje": date(2026, 9, 4), "linhas": [], "total_previsto": Decimal("0.00"), "n_atraso": 0, "n_bloqueio": 0}
    texto = lembrete.montar_texto(agenda)
    assert "não tem ninguém pra cobrar" in texto
    assert "04/09" in texto


@pytest.mark.django_db
def test_texto_lista_atrasados_com_valor_e_alerta(cliente):
    hoje = date(2026, 9, 4)
    atrasado = _contrato(
        cliente,
        apelido="iPhone 13",
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("100.00"),
        proximo_vencimento=hoje - timedelta(days=10),
    )
    agenda = montar_agenda_do_dia(hoje=hoje)
    texto = lembrete.montar_texto(agenda)

    assert "Fulano de Tal" in texto
    assert "iPhone 13" in texto
    assert "10d de atraso" in texto
    assert "⚠ bloquear" in texto  # 10 dias >= gatilho de 7
    assert "R$ 150,00" in texto  # 100 parcela + 50 juros (10 dias x 5)
    assert "1 contrato" in texto
    assert "1 atrasado" in texto


@pytest.mark.django_db
def test_texto_vence_hoje_sem_valor_de_parcela(cliente):
    hoje = date(2026, 9, 4)
    _contrato(
        cliente,
        apelido="Fone JBL",
        estrutura=Contrato.Estrutura.MENSAL,
        proximo_vencimento=hoje,
    )
    agenda = montar_agenda_do_dia(hoje=hoje)
    texto = lembrete.montar_texto(agenda)
    assert "vence hoje" in texto
    assert "—" in texto  # sem valor_parcela


# ── enviar (stub) ─────────────────────────────────────────────────────────

def test_enviar_devolve_true_e_loga(caplog, settings):
    settings.YSLANE_WHATSAPP_NUMERO = "+5583988887777"
    with caplog.at_level(logging.INFO, logger="pagamentos.lembrete"):
        assert lembrete.enviar("texto de teste") is True
    assert "+5583988887777" in caplog.text
    assert "texto de teste" in caplog.text


def test_enviar_sem_numero_configurado_avisa(caplog, settings):
    settings.YSLANE_WHATSAPP_NUMERO = ""
    with caplog.at_level(logging.WARNING, logger="pagamentos.lembrete"):
        assert lembrete.enviar("texto de teste") is True
    assert "não configurado" in caplog.text


def test_enviar_aceita_numero_explicito(caplog):
    with caplog.at_level(logging.INFO, logger="pagamentos.lembrete"):
        lembrete.enviar("texto", numero="+5511900000000")
    assert "+5511900000000" in caplog.text


# ── enviar_lembrete_diario (integração) ──────────────────────────────────

@pytest.mark.django_db
def test_enviar_lembrete_diario_devolve_o_texto_montado(cliente):
    hoje = date(2026, 9, 4)
    _contrato(
        cliente,
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("50.00"),
        proximo_vencimento=hoje - timedelta(days=1),
    )
    texto = lembrete.enviar_lembrete_diario(hoje=hoje)
    assert "Fulano de Tal" in texto
    assert "1d de atraso" in texto


# ── management command ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_comando_mostra_o_texto_do_lembrete(cliente):
    hoje = date(2026, 9, 4)
    _contrato(
        cliente,
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("50.00"),
        proximo_vencimento=hoje,
    )
    out = StringIO()
    call_command("enviar_lembrete_diario", "--hoje", "2026-09-04", stdout=out)
    saida = out.getvalue()
    assert "Lembrete montado" in saida
    assert "Fulano de Tal" in saida
    assert "vence hoje" in saida


@pytest.mark.django_db
def test_comando_sem_ninguem_pra_cobrar():
    out = StringIO()
    call_command("enviar_lembrete_diario", "--hoje", "2026-09-04", stdout=out)
    assert "não tem ninguém pra cobrar" in out.getvalue()


def test_comando_rejeita_hoje_invalido():
    with pytest.raises(CommandError):
        call_command("enviar_lembrete_diario", "--hoje", "04/09/2026")
