"""Testes da Fase 2 — recorrência, model Vencimento, geração e painel "cobrar hoje".

Cobrem as 5 estruturas de pagamento (PLANO-DO-PROJETO.md, seção 5).
"""

import datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos import recorrencia
from apps.pagamentos.models import Vencimento

date = datetime.date
timedelta = datetime.timedelta

INICIO = date(2026, 3, 1)


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


# ── recorrência: as 5 estruturas ─────────────────────────────────────────────

def test_diaria_e_todo_dia():
    assert recorrencia.data_da_parcela(INICIO, "diaria", 1) == date(2026, 3, 2)
    assert recorrencia.data_da_parcela(INICIO, "diaria", 10) == date(2026, 3, 11)


def test_semanal_a_cada_7_dias():
    assert recorrencia.data_da_parcela(INICIO, "semanal", 1) == date(2026, 3, 8)
    assert recorrencia.data_da_parcela(INICIO, "semanal", 3) == date(2026, 3, 22)


def test_dezena_a_cada_10_dias():
    assert recorrencia.data_da_parcela(INICIO, "dezena", 1) == date(2026, 3, 11)
    assert recorrencia.data_da_parcela(INICIO, "dezena", 3) == date(2026, 3, 31)


def test_quinzenal_a_cada_15_dias():
    assert recorrencia.data_da_parcela(INICIO, "quinzenal", 1) == date(2026, 3, 16)
    assert recorrencia.data_da_parcela(INICIO, "quinzenal", 2) == date(2026, 3, 31)


def test_mensal_mesmo_dia_do_mes():
    assert recorrencia.data_da_parcela(date(2026, 3, 15), "mensal", 1) == date(2026, 4, 15)
    assert recorrencia.data_da_parcela(date(2026, 3, 15), "mensal", 2) == date(2026, 5, 15)


def test_mensal_ajusta_mes_curto():
    # 31/01 -> não existe 31/02: cai no último dia de fevereiro.
    assert recorrencia.data_da_parcela(date(2026, 1, 31), "mensal", 1) == date(2026, 2, 28)


def test_numero_de_parcela_comeca_em_1():
    with pytest.raises(ValueError):
        recorrencia.data_da_parcela(INICIO, "diaria", 0)


def test_estrutura_desconhecida_e_erro():
    with pytest.raises(ValueError):
        recorrencia.data_da_parcela(INICIO, "trimestral", 1)


def test_datas_das_parcelas_tem_o_tamanho_certo():
    datas = recorrencia.datas_das_parcelas(date(2026, 1, 10), "mensal", 12)
    assert len(datas) == 12
    assert datas[0] == date(2026, 2, 10)
    assert datas[-1] == date(2027, 1, 10)


def test_data_prevista_quitacao():
    assert recorrencia.data_prevista_quitacao(date(2026, 1, 10), "mensal", 12) == date(2027, 1, 10)
    assert recorrencia.data_prevista_quitacao(INICIO, "dezena", 10) == INICIO + timedelta(days=100)
    assert recorrencia.data_prevista_quitacao(INICIO, "diaria", None) is None


# ── model Vencimento ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_vencimento_unico_por_contrato_e_numero(cliente):
    ct = _contrato(cliente)
    Vencimento.objects.create(
        contrato=ct, numero=1, data_vencimento=date(2026, 3, 2), valor_previsto=Decimal("40.00")
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Vencimento.objects.create(
                contrato=ct, numero=1, data_vencimento=date(2026, 3, 3), valor_previsto=Decimal("40.00")
            )


@pytest.mark.django_db
def test_vencimento_saldo_e_quitada(cliente):
    ct = _contrato(cliente)
    v = Vencimento.objects.create(
        contrato=ct, numero=1, data_vencimento=date(2026, 3, 2), valor_previsto=Decimal("40.00")
    )
    assert v.saldo == Decimal("40.00")
    assert v.quitada is False


# ── Contrato.gerar_vencimentos ───────────────────────────────────────────────

@pytest.mark.django_db
def test_gera_ate_o_horizonte_e_e_idempotente(cliente):
    hoje = date(2026, 3, 1)
    ct = _contrato(
        cliente,
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("40.00"),
        num_parcelas=60,
        data_inicio=date(2026, 2, 20),
    )
    criados = ct.gerar_vencimentos(dias_a_frente=60, hoje=hoje)
    assert len(criados) == 60  # teto de num_parcelas antes do horizonte
    v1 = ct.vencimentos.get(numero=1)
    assert v1.data_vencimento == date(2026, 2, 21)
    assert v1.valor_previsto == Decimal("40.00")
    assert v1.status == Vencimento.Status.ABERTO
    # rodar de novo não recria nada
    assert ct.gerar_vencimentos(dias_a_frente=60, hoje=hoje) == []
    assert ct.vencimentos.count() == 60


@pytest.mark.django_db
def test_geracao_respeita_num_parcelas_como_teto(cliente):
    ct = _contrato(
        cliente,
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("150.00"),
        num_parcelas=3,
        data_inicio=date(2026, 1, 10),
    )
    ct.gerar_vencimentos(dias_a_frente=3650, hoje=date(2026, 1, 1))
    assert [v.data_vencimento for v in ct.vencimentos.all()] == [
        date(2026, 2, 10),
        date(2026, 3, 10),
        date(2026, 4, 10),
    ]


@pytest.mark.django_db
def test_geracao_inclui_parcelas_ja_vencidas(cliente):
    ct = _contrato(
        cliente,
        estrutura=Contrato.Estrutura.SEMANAL,
        valor_parcela=Decimal("100.00"),
        num_parcelas=8,
        data_inicio=date(2026, 1, 1),
    )
    criados = ct.gerar_vencimentos(dias_a_frente=0, hoje=date(2026, 2, 1))
    # +7/+14/+21/+28 = 08, 15, 22, 29 de janeiro; +35 = 05/02 já passa do horizonte
    assert [v.numero for v in criados] == [1, 2, 3, 4]


@pytest.mark.django_db
def test_sem_valor_parcela_nao_gera(cliente):
    ct = _contrato(cliente, valor_parcela=None, num_parcelas=10)
    assert ct.gerar_vencimentos(hoje=date(2026, 3, 1)) == []
    assert ct.vencimentos.count() == 0


@pytest.mark.django_db
def test_contrato_quitado_nao_gera(cliente):
    ct = _contrato(
        cliente, valor_parcela=Decimal("40.00"), num_parcelas=10, status=Contrato.Status.QUITADO
    )
    assert ct.gerar_vencimentos(hoje=date(2026, 3, 1)) == []


# ── Contrato.atualizar_data_prevista_quitacao ────────────────────────────────

@pytest.mark.django_db
def test_atualiza_data_prevista_quitacao(cliente):
    ct = _contrato(
        cliente,
        estrutura=Contrato.Estrutura.MENSAL,
        num_parcelas=12,
        data_inicio=date(2026, 1, 10),
    )
    assert ct.data_prevista_quitacao is None
    assert ct.atualizar_data_prevista_quitacao() is True
    ct.refresh_from_db()
    assert ct.data_prevista_quitacao == date(2027, 1, 10)
    assert ct.atualizar_data_prevista_quitacao() is False  # não muda de novo


@pytest.mark.django_db
def test_sem_num_parcelas_nao_ha_data_de_quitacao(cliente):
    ct = _contrato(cliente, num_parcelas=None)
    assert ct.atualizar_data_prevista_quitacao() is False
    assert ct.data_prevista_quitacao is None


# ── Contrato: parcela × total (aviso) ────────────────────────────────────────

@pytest.mark.django_db
def test_parcelas_conferem(cliente):
    ok = _contrato(
        cliente, valor_total=Decimal("2400.00"), valor_parcela=Decimal("40.00"), num_parcelas=60
    )
    assert ok.parcelas_conferem is True

    diverge = _contrato(
        cliente,
        apelido="B",
        valor_total=Decimal("1800.00"),
        valor_parcela=Decimal("150.00"),
        num_parcelas=10,
    )
    assert diverge.parcelas_conferem is False
    assert diverge.total_das_parcelas == Decimal("1500.00")

    incompleto = _contrato(cliente, apelido="C", valor_parcela=None, num_parcelas=None)
    assert incompleto.parcelas_conferem is None
    assert incompleto.total_das_parcelas is None


@pytest.mark.django_db
def test_form_avisa_quando_parcela_nao_bate(auth_client, cliente):
    from apps.contratos.tests import dados_form

    resp = auth_client.post(
        reverse("contratos:novo"),
        dados_form(cliente, valor_total="1.800,00", valor_parcela="150,00", num_parcelas="10"),
        follow=True,
    )
    corpo = resp.content.decode()
    assert "diferente do valor total" in corpo or "Confira os números" in corpo


# ── management command gerar_vencimentos ─────────────────────────────────────

@pytest.mark.django_db
def test_comando_gera_e_sincroniza_em_massa():
    call_command("seed_demo")
    out = StringIO()
    call_command("gerar_vencimentos", stdout=out)
    texto = out.getvalue()
    assert "contrato(s) processado(s)" in texto
    assert Vencimento.objects.exists()

    # contrato de demo com parcela + nº definidos ganha data prevista de quitação
    ct = (
        Contrato.objects.filter(valor_parcela__isnull=False, num_parcelas__isnull=False)
        .exclude(status=Contrato.Status.QUITADO)
        .first()
    )
    ct.refresh_from_db()
    assert ct.data_prevista_quitacao is not None
    assert ct.vencimentos.count() > 0


@pytest.mark.django_db
def test_comando_e_idempotente():
    call_command("seed_demo")
    call_command("gerar_vencimentos")
    n = Vencimento.objects.count()
    call_command("gerar_vencimentos")
    assert Vencimento.objects.count() == n


@pytest.mark.django_db
def test_comando_rejeita_dias_invalido():
    with pytest.raises(CommandError):
        call_command("gerar_vencimentos", "--dias", "0")


@pytest.mark.django_db
def test_comando_rejeita_hoje_invalido():
    with pytest.raises(CommandError):
        call_command("gerar_vencimentos", "--hoje", "03/09/2026")


# ── painel "cobrar hoje" ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cobrar_hoje_exige_login(client):
    resp = client.get(reverse("pagamentos:cobrar_hoje"))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_cobrar_hoje_lista_atrasado_e_ignora_quitado_e_futuro(auth_client, cliente):
    hoje = date.today()
    _contrato(
        cliente,
        apelido="Atrasado",
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("100.00"),
        proximo_vencimento=hoje - timedelta(days=5),
    )
    _contrato(
        cliente,
        apelido="Futuro",
        estrutura=Contrato.Estrutura.MENSAL,
        proximo_vencimento=hoje + timedelta(days=10),
    )
    _contrato(
        cliente,
        apelido="Quitado",
        status=Contrato.Status.QUITADO,
        proximo_vencimento=hoje - timedelta(days=90),
    )
    resp = auth_client.get(reverse("pagamentos:cobrar_hoje"))
    assert resp.status_code == 200
    apelidos = {linha["contrato"].apelido for linha in resp.context["linhas"]}
    assert apelidos == {"Atrasado"}
    assert resp.context["n_atraso"] == 1


@pytest.mark.django_db
def test_cobrar_hoje_inclui_quem_vence_hoje(auth_client, cliente):
    hoje = date.today()
    _contrato(
        cliente,
        apelido="VenceHoje",
        estrutura=Contrato.Estrutura.MENSAL,
        proximo_vencimento=hoje,
    )
    resp = auth_client.get(reverse("pagamentos:cobrar_hoje"))
    linhas = resp.context["linhas"]
    assert [linha["contrato"].apelido for linha in linhas] == ["VenceHoje"]
    assert linhas[0]["vence_hoje"] is True


@pytest.mark.django_db
def test_cobrar_hoje_vazio(auth_client, cliente):
    _contrato(
        cliente,
        apelido="Futuro",
        estrutura=Contrato.Estrutura.MENSAL,
        proximo_vencimento=date.today() + timedelta(days=30),
    )
    resp = auth_client.get(reverse("pagamentos:cobrar_hoje"))
    assert list(resp.context["linhas"]) == []
    assert "Nada para cobrar hoje" in resp.content.decode()
