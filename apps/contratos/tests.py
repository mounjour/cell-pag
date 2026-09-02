import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.forms import moeda_para_decimal
from apps.contratos.models import Contrato


def dados_form(cliente, **over):
    dados = {
        "cliente": cliente.pk,
        "apelido": "iPhone 11",
        "aparelho_modelo": "iPhone 11 64GB",
        "imei": "",
        "valor_total": "2400,00",
        "estrutura": Contrato.Estrutura.DIARIA,
        "valor_parcela": "",
        "num_parcelas": "",
        "data_inicio": "2026-08-01",
        "dia_referencia": "",
        "proximo_vencimento": "",
        "status": Contrato.Status.EM_DIA,
        "data_prevista_quitacao": "",
        "observacoes": "",
    }
    dados.update(over)
    return dados


@pytest.fixture
def cliente(db):
    c = Cliente(nome="Cliente Teste", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    c.full_clean()
    c.save()
    return c


def novo_contrato(cliente, **kwargs):
    dados = dict(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        valor_total="2400.00",
        estrutura=Contrato.Estrutura.DIARIA,
        data_inicio=datetime.date(2026, 8, 1),
    )
    dados.update(kwargs)
    return Contrato.objects.create(**dados)


# ---------- Modelo ----------

@pytest.mark.django_db
def test_contrato_minimo(cliente):
    ct = novo_contrato(cliente)
    assert ct.status == Contrato.Status.EM_DIA
    assert ct.valor_parcela is None  # cálculo é da Fase 2
    assert ct.proximo_vencimento is None
    assert not ct.quitado
    assert str(ct) == "Cliente Teste — iPhone 11"


# ---------- Modelo: ligação com o cálculo de atraso (Fase 4) ----------

@pytest.mark.django_db
def test_situacao_atraso_sem_proximo_vencimento_e_none(cliente):
    ct = novo_contrato(cliente)
    assert ct.situacao_atraso() is None
    # status_efetivo cai no status salvo quando não há data de referência
    assert ct.status_efetivo == ct.status


@pytest.mark.django_db
def test_situacao_atraso_em_dia(cliente):
    hoje = datetime.date(2026, 9, 10)
    ct = novo_contrato(cliente, proximo_vencimento=hoje, estrutura=Contrato.Estrutura.MENSAL)
    s = ct.situacao_atraso(hoje=hoje)
    assert s.dias_atraso == 0
    assert s.status == Contrato.Status.EM_DIA
    assert s.juros == Decimal("0.00")
    assert s.alertar_bloqueio is False


@pytest.mark.django_db
def test_situacao_atraso_atrasado_com_juros(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 9, 10),
        estrutura=Contrato.Estrutura.MENSAL,
    )
    s = ct.situacao_atraso(hoje=datetime.date(2026, 9, 13))
    assert s.dias_atraso == 3
    assert s.juros == Decimal("15.00")
    assert s.status == Contrato.Status.ATRASADO
    assert s.alertar_bloqueio is False


@pytest.mark.django_db
def test_situacao_atraso_inadimplente_dispara_alerta(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 9, 1),
        estrutura=Contrato.Estrutura.DIARIA,
    )
    s = ct.situacao_atraso(hoje=datetime.date(2026, 9, 11))
    assert s.dias_atraso == 10
    assert s.status == Contrato.Status.INADIMPLENTE
    assert s.alertar_bloqueio is True


@pytest.mark.django_db
def test_situacao_atraso_semanal_usa_a_janela(cliente):
    # Vencimento numa quarta (2026-01-07); a semana fecha no domingo 2026-01-11.
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 1, 7),
        estrutura=Contrato.Estrutura.SEMANAL,
    )
    assert ct.situacao_atraso(hoje=datetime.date(2026, 1, 11)).dias_atraso == 0
    assert ct.situacao_atraso(hoje=datetime.date(2026, 1, 12)).dias_atraso == 1


@pytest.mark.django_db
def test_situacao_atraso_quitado_nao_cobra(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 1, 1),
        status=Contrato.Status.QUITADO,
    )
    s = ct.situacao_atraso(hoje=datetime.date(2026, 6, 1))
    assert s.status == Contrato.Status.QUITADO
    assert s.juros == Decimal("0.00")
    assert s.alertar_bloqueio is False


@pytest.mark.django_db
def test_sincronizar_status_grava_o_calculado(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 9, 1),
        estrutura=Contrato.Estrutura.MENSAL,
    )
    mudou = ct.sincronizar_status(hoje=datetime.date(2026, 9, 5))
    assert mudou is True
    ct.refresh_from_db()
    assert ct.status == Contrato.Status.ATRASADO
    # segunda chamada no mesmo dia não muda nada
    assert ct.sincronizar_status(hoje=datetime.date(2026, 9, 5)) is False


@pytest.mark.django_db
def test_sincronizar_status_sem_data_nao_mexe(cliente):
    ct = novo_contrato(cliente, status=Contrato.Status.ATRASADO)
    assert ct.sincronizar_status() is False
    ct.refresh_from_db()
    assert ct.status == Contrato.Status.ATRASADO


@pytest.mark.django_db
def test_detalhe_mostra_situacao_hoje(auth_client, cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2020, 1, 1),  # bem no passado
        estrutura=Contrato.Estrutura.MENSAL,
    )
    resp = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]))
    corpo = resp.content.decode()
    assert "Situação hoje" in corpo
    assert "de atraso" in corpo


# ---------- Telas ----------

@pytest.mark.django_db
def test_lista_exige_login(client):
    resp = client.get(reverse("contratos:lista"))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_lista_filtra_por_status(auth_client, cliente):
    novo_contrato(cliente, apelido="A", status=Contrato.Status.EM_DIA)
    novo_contrato(cliente, apelido="B", status=Contrato.Status.ATRASADO)
    resp = auth_client.get(reverse("contratos:lista"), {"status": "atrasado"})
    apelidos = {c.apelido for c in resp.context["contratos"]}
    assert apelidos == {"B"}


@pytest.mark.django_db
def test_lista_usa_status_calculado_no_badge_e_no_filtro(auth_client, cliente):
    # `status` salvo diz "em dia", mas o vencimento está bem no passado:
    # a lista deve mostrar/filtrar pelo status calculado (inadimplente).
    novo_contrato(
        cliente,
        apelido="Atrasadão",
        status=Contrato.Status.EM_DIA,
        estrutura=Contrato.Estrutura.MENSAL,
        proximo_vencimento=datetime.date(2020, 1, 1),
    )
    corpo = auth_client.get(reverse("contratos:lista")).content.decode()
    assert "INADIMPLENTE" in corpo.upper()

    achados = auth_client.get(reverse("contratos:lista"), {"status": "inadimplente"})
    assert [c.apelido for c in achados.context["contratos"]] == ["Atrasadão"]

    vazio = auth_client.get(reverse("contratos:lista"), {"status": "em_dia"})
    assert list(vazio.context["contratos"]) == []


@pytest.mark.django_db
def test_detalhe_renderiza(auth_client, cliente):
    ct = novo_contrato(cliente)
    resp = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]))
    assert resp.status_code == 200
    assert resp.context["contrato"] == ct
    assert "form_documento" in resp.context


@pytest.mark.django_db
def test_novo_contrato_pre_preenche_cliente(auth_client, cliente):
    resp = auth_client.get(reverse("contratos:novo") + f"?cliente={cliente.pk}")
    assert resp.status_code == 200
    assert resp.context["form"].initial.get("cliente") == cliente


@pytest.mark.django_db
def test_editar_contrato(auth_client, cliente):
    ct = novo_contrato(cliente)
    resp = auth_client.post(
        reverse("contratos:editar", args=[ct.pk]),
        dados_form(cliente, apelido="iPhone 11 Pro", estrutura=Contrato.Estrutura.SEMANAL),
    )
    assert resp.status_code == 302
    ct.refresh_from_db()
    assert ct.apelido == "iPhone 11 Pro"
    assert ct.estrutura == Contrato.Estrutura.SEMANAL


# ---------- Formulário: entrada de dados no celular ----------

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("1.234,56", Decimal("1234.56")),
        ("1234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("2400", Decimal("2400")),
        ("", None),
    ],
)
def test_moeda_para_decimal(entrada, esperado):
    assert moeda_para_decimal(entrada) == esperado


@pytest.mark.django_db
def test_form_aceita_valor_com_virgula(auth_client, cliente):
    resp = auth_client.post(
        reverse("contratos:novo"),
        dados_form(cliente, valor_total="1.899,90", valor_parcela="63,33"),
    )
    assert resp.status_code == 302
    ct = Contrato.objects.get()
    assert ct.valor_total == Decimal("1899.90")
    assert ct.valor_parcela == Decimal("63.33")


@pytest.mark.django_db
def test_form_valor_invalido_mostra_erro(auth_client, cliente):
    resp = auth_client.post(reverse("contratos:novo"), dados_form(cliente, valor_total="abc"))
    assert resp.status_code == 200
    assert "valor_total" in resp.context["form"].errors
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_form_normaliza_imei(auth_client, cliente):
    resp = auth_client.post(
        reverse("contratos:novo"),
        dados_form(cliente, imei="35 999905 337250 1"),
    )
    assert resp.status_code == 302
    assert Contrato.objects.get().imei == "359999053372501"


@pytest.mark.django_db
def test_anexar_documento_registra_enviado_por(auth_client, operador, cliente, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    ct = novo_contrato(cliente, apelido="A", estrutura=Contrato.Estrutura.SEMANAL)
    arquivo = SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 conteudo", content_type="application/pdf")
    resp = auth_client.post(
        reverse("contratos:documento_novo", args=[ct.pk]),
        {"tipo": "contrato_assinado", "descricao": "assinado", "arquivo": arquivo},
    )
    assert resp.status_code == 302
    doc = ct.documentos.get()
    assert doc.enviado_por == operador
    assert doc.tipo == "contrato_assinado"


# ---------- Comando seed_demo ----------

@pytest.mark.django_db
def test_seed_demo_cria_massa_variada():
    call_command("seed_demo")
    assert Cliente.objects.count() == 10
    assert Contrato.objects.count() == 10

    # Um cliente fica sem contrato de propósito.
    assert Cliente.objects.filter(contratos__isnull=True).count() == 1

    # As 5 estruturas aparecem.
    estruturas = set(Contrato.objects.values_list("estrutura", flat=True))
    assert estruturas == {e.value for e in Contrato.Estrutura}

    # Situações-chave: um quitado, um sem próximo vencimento, e pelo menos um
    # inadimplente com alerta de bloqueio pelo cálculo de hoje.
    assert Contrato.objects.filter(status=Contrato.Status.QUITADO).count() == 1
    assert Contrato.objects.filter(proximo_vencimento__isnull=True).count() == 1
    situacoes = [ct.situacao_atraso() for ct in Contrato.objects.all()]
    assert any(s and s.alertar_bloqueio for s in situacoes)


@pytest.mark.django_db
def test_seed_demo_idempotente_e_reset():
    call_command("seed_demo")
    call_command("seed_demo")  # rodar de novo não duplica
    assert Cliente.objects.count() == 10
    assert Contrato.objects.count() == 10

    call_command("seed_demo", "--reset")
    assert Cliente.objects.count() == 10
    assert Contrato.objects.count() == 10
