import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato


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
    dados = {
        "cliente": cliente.pk,
        "apelido": "iPhone 11 Pro",
        "aparelho_modelo": ct.aparelho_modelo,
        "imei": "",
        "valor_total": "2400.00",
        "estrutura": Contrato.Estrutura.SEMANAL,
        "valor_parcela": "",
        "num_parcelas": "",
        "data_inicio": "2026-08-01",
        "dia_referencia": "",
        "fiador": "",
        "status": Contrato.Status.EM_DIA,
        "data_prevista_quitacao": "",
        "observacoes": "",
    }
    resp = auth_client.post(reverse("contratos:editar", args=[ct.pk]), dados)
    assert resp.status_code == 302
    ct.refresh_from_db()
    assert ct.apelido == "iPhone 11 Pro"
    assert ct.estrutura == Contrato.Estrutura.SEMANAL


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
