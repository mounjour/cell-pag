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


@pytest.fixture
def operador(django_user_model):
    return django_user_model.objects.create_user("op", password="s3nha-forte-123")


@pytest.mark.django_db
def test_contrato_minimo(cliente):
    ct = Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        valor_total="2400.00",
        estrutura=Contrato.Estrutura.DIARIA,
        data_inicio=datetime.date(2026, 8, 1),
    )
    assert ct.status == Contrato.Status.EM_DIA
    assert ct.valor_parcela is None  # cálculo é da Fase 2
    assert str(ct) == "Cliente Teste — iPhone 11"


@pytest.mark.django_db
def test_novo_contrato_pre_preenche_cliente(client, operador, cliente):
    client.force_login(operador)
    resp = client.get(reverse("contratos:novo") + f"?cliente={cliente.pk}")
    assert resp.status_code == 200
    assert resp.context["form"].initial.get("cliente") == cliente


@pytest.mark.django_db
def test_anexar_documento_registra_enviado_por(client, operador, cliente, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    ct = Contrato.objects.create(
        cliente=cliente,
        apelido="A",
        aparelho_modelo="Modelo A",
        valor_total="1000.00",
        estrutura=Contrato.Estrutura.SEMANAL,
        data_inicio=datetime.date(2026, 8, 1),
    )
    client.force_login(operador)
    arquivo = SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 conteudo", content_type="application/pdf")
    resp = client.post(
        reverse("contratos:documento_novo", args=[ct.pk]),
        {"tipo": "contrato_assinado", "descricao": "assinado", "arquivo": arquivo},
    )
    assert resp.status_code == 302
    doc = ct.documentos.get()
    assert doc.enviado_por == operador
    assert doc.tipo == "contrato_assinado"
