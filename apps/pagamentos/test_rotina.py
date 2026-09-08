"""Testes do comando `rotina_diaria` — o que o cron do Render chama 1x/dia.

Com os provedores no padrão ``log`` (WhatsApp e Cora), a rotina só monta as
filas e registra no log; aqui garantimos que ela roda as três etapas na ordem
e propaga a falha de uma etapa sem abortar as demais.
"""

import datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato

date = datetime.date


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
        valor_parcela=Decimal("40.00"),
        num_parcelas=60,
        data_inicio=date(2026, 8, 1),
    )
    dados.update(kwargs)
    return Contrato.objects.create(**dados)


@pytest.mark.django_db
def test_rotina_roda_as_tres_etapas_em_ordem(cliente):
    _contrato(cliente)
    out = StringIO()
    call_command("rotina_diaria", "--hoje", "2026-09-08", stdout=out, stderr=StringIO())
    texto = out.getvalue()
    assert texto.index("gerar_vencimentos") < texto.index("enviar_lembrete_diario")
    assert texto.index("enviar_lembrete_diario") < texto.index("enviar_cobrancas_clientes")
    assert "[OK] Rotina diária concluída." in texto


@pytest.mark.django_db
def test_rotina_gera_vencimentos_do_contrato(cliente):
    ct = _contrato(cliente)
    assert ct.vencimentos.count() == 0
    call_command("rotina_diaria", "--hoje", "2026-09-08", stdout=StringIO(), stderr=StringIO())
    assert ct.vencimentos.count() > 0


@pytest.mark.django_db
def test_sem_cobrancas_pula_a_ultima_etapa(cliente):
    _contrato(cliente)
    out = StringIO()
    call_command(
        "rotina_diaria", "--hoje", "2026-09-08", "--sem-cobrancas",
        stdout=out, stderr=StringIO(),
    )
    assert "enviar_cobrancas_clientes" not in out.getvalue()


@pytest.mark.django_db
def test_data_invalida_e_erro(cliente):
    with pytest.raises(CommandError):
        call_command("rotina_diaria", "--hoje", "08/09/2026", stdout=StringIO(), stderr=StringIO())


@pytest.mark.django_db
def test_falha_de_uma_etapa_nao_derruba_as_outras(cliente, monkeypatch):
    _contrato(cliente)

    def explode(*a, **k):
        raise RuntimeError("Cora fora do ar")

    monkeypatch.setattr("apps.pagamentos.cobranca.montar_agenda_do_dia", explode)
    out, err = StringIO(), StringIO()
    with pytest.raises(CommandError) as exc:
        call_command("rotina_diaria", "--hoje", "2026-09-08", stdout=out, stderr=err)
    assert "enviar_cobrancas_clientes" in str(exc.value)
    # as duas primeiras etapas ainda apareceram
    assert "gerar_vencimentos" in out.getvalue()
    assert "enviar_lembrete_diario" in out.getvalue()
