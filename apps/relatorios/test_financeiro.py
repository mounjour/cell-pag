"""Dashboard financeiro: acesso só do dono e números que batem com Relatórios, Início e cobrança."""

import datetime
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import Pagamento, RecebimentoCora, Vencimento
from apps.relatorios.dashboard import FAIXAS_DE_ATRASO, montar_dashboard, periodo_anterior, variacao
from apps.relatorios.tests import dono, dono_client  # noqa: F401  (fixtures)


@pytest.fixture
def financeiro_client(operador):
    """Cliente de teste separado, logado com o perfil financeiro (o ``auth_client`` divide o cliente com o dono)."""
    c = Client()
    c.force_login(operador)
    return c

pytestmark = pytest.mark.django_db


def _contrato(nome, cpf, atraso, valor_parcela="100.00"):
    hoje = timezone.localdate()
    cliente = Cliente.objects.create(nome=nome, cpf=cpf, telefone_whatsapp="+5583999991000")
    contrato = Contrato.objects.create(
        cliente=cliente, apelido="iPhone", aparelho_modelo="iPhone", valor_total=Decimal("1000.00"),
        estrutura=Contrato.Estrutura.DIARIA, valor_parcela=Decimal(valor_parcela), num_parcelas=10,
        data_inicio=hoje - datetime.timedelta(days=atraso + 1), juros_diario=Decimal("5.00"),
    )
    venc = Vencimento.objects.create(
        contrato=contrato, numero=1, valor_previsto=Decimal(valor_parcela), data_vencimento=hoje - datetime.timedelta(days=atraso),
    )
    return contrato, venc


def test_so_o_dono_ve_o_dashboard(financeiro_client, dono_client):
    assert Client().get(reverse("relatorios:financeiro")).status_code == 302
    assert financeiro_client.get(reverse("relatorios:financeiro")).status_code == 403  # perfil financeiro
    assert dono_client.get(reverse("relatorios:financeiro")).status_code == 200


def test_variacao_e_periodo_anterior():
    assert variacao(Decimal("150"), Decimal("100")) == Decimal("50.0")
    assert variacao(Decimal("50"), Decimal("100")) == Decimal("-50.0")
    assert variacao(Decimal("50"), Decimal("0")) is None
    ini, fim = periodo_anterior(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
    assert (ini, fim) == (datetime.date(2026, 10, 2), datetime.date(2026, 10, 31))  # 30 dias antes, sem sobrepor


def test_numeros_do_periodo_atraso_por_faixa_e_extrato():
    hoje = timezone.localdate()
    c1, v1 = _contrato("Ana Atrasada", "52998224725", atraso=3)    # 1 a 7 dias
    c2, v2 = _contrato("Bia Muito Atrasada", "11144477735", atraso=20)  # 16 a 30 dias
    Pagamento(contrato=c1, vencimento=v1, data_pagamento=hoje, valor_pago=Decimal("40.00"), juros_pago=Decimal("5.00"), forma="pix").registrar()  # parcial
    RecebimentoCora.objects.create(entrada_id="e1", valor=Decimal("77.00"), recebido_em=timezone.now(), nome="Fulano")

    d = montar_dashboard(hoje.replace(day=1), hoje, hoje)
    assert d["recebido"] == Decimal("40.00") and d["juros_recebidos"] == Decimal("5.00") and d["entrou"] == Decimal("45.00")
    faixas = {f["rotulo"]: f for f in d["atraso"]["faixas"]}
    assert faixas["1 a 7 dias"]["parcelas"] == 1 and faixas["16 a 30 dias"]["parcelas"] == 1
    # Ana: saldo 60 (a parcial continua cobrada) + 3 dias × 5; Bia: 100 + 20 × 5
    assert faixas["1 a 7 dias"]["saldo"] == Decimal("60.00") and faixas["1 a 7 dias"]["juros"] == Decimal("15.00")
    assert faixas["16 a 30 dias"]["total"] == Decimal("200.00")
    assert d["atraso"]["total"] == Decimal("275.00") and d["atraso"]["contratos_em_atraso"] == 2
    assert [x["contrato"].cliente.nome for x in d["atraso"]["devedores"]] == ["Bia Muito Atrasada", "Ana Atrasada"]  # maior primeiro
    assert d["extrato_sem_baixa_n"] == 1 and d["extrato_sem_baixa_valor"] == Decimal("77.00")
    assert [f[0] for f in FAIXAS_DE_ATRASO][0] == "1 a 7 dias" and d["por_forma"][0]["forma_label"] == "Pix"


def test_tela_mostra_os_blocos_e_os_dados_dos_graficos(dono_client):
    hoje = timezone.localdate()
    contrato, venc = _contrato("Carla", "39053344705", atraso=2)
    Pagamento(contrato=contrato, vencimento=venc, data_pagamento=hoje, valor_pago=Decimal("100.00"), forma="dinheiro").registrar()
    html = dono_client.get(reverse("relatorios:financeiro")).content.decode()
    for trecho in (
        "Entrou no período", "Previsto até hoje", "Quem está devendo hoje", "Por forma de pagamento", "De onde veio o recebido",
        "Carteira a receber", "Por frequência de pagamento", "Quem mais pagou no período", "Agenda e previsão", "Alertas e pendências",
        'id="fin-entradas"', 'id="fin-meses"', "fin-entradas-data",
    ):
        assert trecho in html
    # período longo: as entradas viram por mês
    longo = dono_client.get(reverse("relatorios:financeiro"), {"periodo": "personalizado", "inicio": (hoje - datetime.timedelta(days=200)).isoformat(), "fim": hoje.isoformat()})
    assert "Entradas por mês" in longo.content.decode()
    # datas inválidas não quebram a tela
    assert dono_client.get(reverse("relatorios:financeiro"), {"periodo": "personalizado", "inicio": "2026-12-01", "fim": "2026-11-01"}).status_code == 200


def test_periodo_futuro_nao_quebra(dono_client):
    amanha = timezone.localdate() + datetime.timedelta(days=1)
    r = dono_client.get(reverse("relatorios:financeiro"), {"periodo": "personalizado", "inicio": amanha.isoformat(), "fim": (amanha + datetime.timedelta(days=5)).isoformat()})
    assert r.status_code == 200 and "o período ainda não começou" in r.content.decode()


def test_menu_mostra_financeiro_so_para_o_dono(financeiro_client, dono_client):
    assert reverse("relatorios:financeiro") not in financeiro_client.get(reverse("relatorios:inicio")).content.decode()
    assert reverse("relatorios:financeiro") in dono_client.get(reverse("relatorios:inicio")).content.decode()


def test_previsto_ate_hoje_realizado_e_quadro_por_frequencia():
    hoje = timezone.localdate()
    c1, v1 = _contrato("Ana Diaria", "52998224725", atraso=2)
    Pagamento(contrato=c1, vencimento=v1, data_pagamento=hoje, valor_pago=Decimal("60.00"), forma="pix").registrar()
    futuro = Vencimento.objects.create(contrato=c1, numero=2, valor_previsto=Decimal("100.00"), data_vencimento=hoje + datetime.timedelta(days=5))

    d = montar_dashboard(hoje - datetime.timedelta(days=10), hoje + datetime.timedelta(days=10), hoje)
    assert d["previsto"] == Decimal("200.00") and d["previsto_ate_hoje"] == Decimal("100.00")  # a parcela 2 ainda vai vencer
    assert d["taxa_realizada"] == Decimal("60.0") and d["situacao_do_previsto"] == "abaixo"
    diario = next(l for l in d["por_periodicidade"] if l["rotulo"] == "Diário")
    assert diario["contratos"] == 1 and diario["recebido"] == Decimal("60.00") and diario["participacao"] == Decimal("100.0")
    assert d["por_periodicidade"][-1]["rotulo"] == "Total" and d["por_periodicidade"][-1]["recebido"] == Decimal("60.00")
    assert [r["nome"] for r in d["ranking"]] == ["Ana Diaria"] and d["ranking"][0]["total"] == Decimal("60.00")
    assert futuro.pk  # só para deixar claro que a parcela futura existe no banco


def test_carteira_total_soma_as_parcelas_ja_geradas_e_as_por_gerar():
    hoje = timezone.localdate()
    contrato, venc = _contrato("Beto Carteira", "11144477735", atraso=0)  # 10 parcelas de 100, só 1 gerada
    d = montar_dashboard(hoje.replace(day=1), hoje, hoje)
    c = d["carteira"]
    assert c["a_receber_gerado"] == Decimal("100.00") and c["a_receber_futuro"] == Decimal("900.00")
    assert c["a_receber_total"] == Decimal("1000.00") and c["ativos"] == 1
    assert c["receita_por_dia"] == Decimal("100.00") and c["n_diarios"] == 1


def test_alertas_trazem_gravidade_e_somem_quando_esta_tudo_em_ordem():
    hoje = timezone.localdate()
    vazio = {a["indicador"]: a for a in montar_dashboard(hoje.replace(day=1), hoje, hoje)["alertas"]}
    assert vazio["Contratos em atraso"]["nivel"] == "ok" and vazio["Rotinas agendadas com problema"]["nivel"] == "ok"
    _contrato("Caio Atrasado", "39053344705", atraso=5)
    RecebimentoCora.objects.create(entrada_id="x9", valor=Decimal("10.00"), recebido_em=timezone.now(), nome="Fulano")
    cheio = {a["indicador"]: a for a in montar_dashboard(hoje.replace(day=1), hoje, hoje)["alertas"]}
    assert cheio["Contratos em atraso"]["nivel"] == "critico" and cheio["Contratos em atraso"]["valor"] == "1"
    assert cheio["Valor em atraso (parcelas e juros)"]["dinheiro"] is True
    assert cheio["Entradas no extrato sem pagamento registrado"]["nivel"] == "atencao"


def test_agenda_totais_de_7_e_30_dias_e_potencial():
    hoje = timezone.localdate()
    contrato, venc = _contrato("Dani Agenda", "11144477735", atraso=3)
    Vencimento.objects.create(contrato=contrato, numero=2, valor_previsto=Decimal("100.00"), data_vencimento=hoje + datetime.timedelta(days=3))
    Vencimento.objects.create(contrato=contrato, numero=3, valor_previsto=Decimal("100.00"), data_vencimento=hoje + datetime.timedelta(days=20))
    d = montar_dashboard(hoje.replace(day=1), hoje, hoje)
    assert d["agenda"]["total_7"] == Decimal("100.00") and d["agenda"]["total"] == Decimal("200.00") and d["agenda"]["quantidade"] == 2
    assert d["potencial_30_dias"] == d["agenda"]["total"] + d["atraso"]["total"]
    assert [p["cliente"].nome for p in d["agenda"]["proximas"]] == ["Dani Agenda", "Dani Agenda"]
