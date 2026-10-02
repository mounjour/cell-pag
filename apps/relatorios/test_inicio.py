import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import Pagamento, Vencimento
from apps.relatorios.servicos import montar_hoje

date = datetime.date


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def _contrato_atrasado(nome, dias, valor="100.00"):
    hoje = date(2026, 10, 2)
    cliente = Cliente.objects.create(
        nome=nome, cpf=CPFGen().generate(), telefone_whatsapp="+5583999991000"
    )
    contrato = Contrato.objects.create(
        cliente=cliente,
        apelido=f"Aparelho de {nome}",
        aparelho_modelo="Modelo",
        valor_total=Decimal(valor),
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal(valor),
        num_parcelas=1,
        data_inicio=hoje - datetime.timedelta(days=dias + 1),
    )
    Vencimento.objects.create(
        contrato=contrato,
        numero=1,
        data_vencimento=hoje - datetime.timedelta(days=dias),
        valor_previsto=Decimal(valor),
    )
    return contrato


@pytest.mark.django_db
def test_montar_hoje_ordena_a_fila_pelo_maior_atraso():
    _contrato_atrasado("Pouco Atraso", 2)
    _contrato_atrasado("Muito Atraso", 20)
    hoje = montar_hoje(date(2026, 10, 2))
    assert hoje["a_cobrar_n"] == 2
    assert [l["contrato"].cliente.nome for l in hoje["fila"]] == ["Muito Atraso", "Pouco Atraso"]
    assert hoje["fila_restante"] == 0


@pytest.mark.django_db
def test_montar_hoje_limita_a_fila_e_conta_o_resto():
    for i in range(5):
        _contrato_atrasado(f"Cliente {i}", i + 1)
    hoje = montar_hoje(date(2026, 10, 2), limite_fila=3)
    assert hoje["a_cobrar_n"] == 5
    assert len(hoje["fila"]) == 3
    assert hoje["fila_restante"] == 2


@pytest.mark.django_db
def test_montar_hoje_soma_o_recebido_de_hoje():
    contrato = _contrato_atrasado("Quem Pagou", 1)
    Pagamento(
        contrato=contrato,
        vencimento=contrato.vencimentos.get(),
        data_pagamento=date(2026, 10, 2),
        valor_pago=Decimal("100.00"),
    ).registrar()
    hoje = montar_hoje(date(2026, 10, 2))
    assert hoje["recebido_hoje"] == Decimal("100.00")
    assert hoje["recebido_hoje_n"] == 1


@pytest.mark.django_db
def test_inicio_mostra_o_que_pede_acao_antes_dos_numeros(auth_client, monkeypatch):
    monkeypatch.setattr("apps.pagamentos.whatsapp.obter_status_conexao", lambda: "open")
    _contrato_atrasado("Fila Visivel", 3)
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert "Quem cobrar agora" in html and "Fila Visivel" in html
    assert html.index("hoje-faixa") < html.index("fila-acao") < html.index("kpi-faixa") < html.index("graficos-recolhiveis")
    assert "data-whatsapp-tile" in html


@pytest.mark.django_db
def test_inicio_sem_cobrancas_diz_que_esta_tudo_em_dia(auth_client):
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert "Nada para cobrar agora" in html
