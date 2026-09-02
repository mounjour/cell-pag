import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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
    assert not ct.quitado
    assert str(ct) == "Cliente Teste — iPhone 11"


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
