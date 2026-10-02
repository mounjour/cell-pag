from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from validate_docbr import CPF as CPFGen

from .models import Aparelho


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("op", password="s3nha-forte-123")


@pytest.fixture
def auth_client(client, usuario):
    client.force_login(usuario)
    return client


@pytest.fixture
def cliente(db):
    c = Cliente(nome="Cliente Teste", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    c.full_clean()
    c.save()
    return c


# ---------- Modelo ----------

@pytest.mark.django_db
def test_aparelho_sem_contrato_esta_disponivel():
    ap = Aparelho.objects.create(modelo="iPhone 11")
    assert ap.status == Aparelho.Status.DISPONIVEL
    assert ap.vendido is False


@pytest.mark.django_db
def test_aparelho_vinculado_a_contrato_fica_vendido(cliente):
    ap = Aparelho.objects.create(modelo="iPhone 11")
    Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        aparelho=ap,
        valor_total=Decimal("1000.00"),
        estrutura=Contrato.Estrutura.MENSAL,
        data_inicio="2026-09-01",
    )
    ap.refresh_from_db()
    assert ap.status == Aparelho.Status.VENDIDO
    assert ap.vendido is True


@pytest.mark.django_db
def test_imei_vazio_vira_none_nao_quebra_unicidade():
    Aparelho.objects.create(modelo="A")
    Aparelho.objects.create(modelo="B")  # dois com IMEI vazio — não pode colidir
    assert Aparelho.objects.count() == 2


@pytest.mark.django_db
def test_dois_aparelhos_com_mesmo_imei_e_recusado():
    from django.db import IntegrityError, transaction

    Aparelho.objects.create(modelo="A", imei="123456789012345")
    with pytest.raises(IntegrityError), transaction.atomic():
        Aparelho.objects.create(modelo="B", imei="123456789012345")


@pytest.mark.django_db
def test_vendido_nao_pode_ser_excluido(cliente):
    ap = Aparelho.objects.create(modelo="iPhone 11")
    Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        aparelho=ap,
        valor_total=Decimal("1000.00"),
        estrutura=Contrato.Estrutura.MENSAL,
        data_inicio="2026-09-01",
    )
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        ap.delete()


# ---------- Views ----------

@pytest.mark.django_db
def test_cadastra_aparelho(auth_client):
    resp = auth_client.post(
        reverse("aparelhos:novo"),
        {
            "modelo": "iPhone 11",
            "imei": "123456789012345",
            "custo": "1.500,00",
            "fornecedor": "Distribuidora X",
            "data_compra": "2026-09-01",
            "observacoes": "",
        },
        follow=True,
    )
    assert resp.status_code == 200
    ap = Aparelho.objects.get(modelo="iPhone 11")
    assert ap.imei == "123456789012345"
    assert ap.custo == Decimal("1500.00")
    assert ap.status == Aparelho.Status.DISPONIVEL


@pytest.mark.django_db
def test_lista_filtra_por_status(auth_client):
    disponivel = Aparelho.objects.create(modelo="Disponível")
    cliente = Cliente.objects.create(
        nome="Fulano", cpf=CPFGen().generate(), telefone_whatsapp="+5583999991111"
    )
    vendido = Aparelho.objects.create(modelo="Vendido")
    Contrato.objects.create(
        cliente=cliente,
        apelido="Vendido",
        aparelho_modelo="Vendido",
        aparelho=vendido,
        valor_total=Decimal("500.00"),
        estrutura=Contrato.Estrutura.MENSAL,
        data_inicio="2026-09-01",
    )

    resp_disp = auth_client.get(reverse("aparelhos:lista"), {"status": "disponivel"})
    nomes = [a.modelo for a in resp_disp.context["aparelhos"]]
    assert nomes == ["Disponível"]

    resp_vend = auth_client.get(reverse("aparelhos:lista"), {"status": "vendido"})
    nomes = [a.modelo for a in resp_vend.context["aparelhos"]]
    assert nomes == ["Vendido"]


@pytest.mark.django_db
def test_busca_por_imei(auth_client):
    Aparelho.objects.create(modelo="iPhone 11", imei="999888777666555")
    Aparelho.objects.create(modelo="Galaxy S21", imei="111222333444555")
    resp = auth_client.get(reverse("aparelhos:lista"), {"q": "999888"})
    nomes = [a.modelo for a in resp.context["aparelhos"]]
    assert nomes == ["iPhone 11"]


@pytest.mark.django_db
def test_excluir_disponivel_funciona(auth_client):
    ap = Aparelho.objects.create(modelo="Sobra de estoque")
    resp = auth_client.post(reverse("aparelhos:excluir", args=[ap.pk]), follow=True)
    assert resp.status_code == 200
    assert not Aparelho.objects.filter(pk=ap.pk).exists()


@pytest.mark.django_db
def test_excluir_vendido_e_recusado(auth_client, cliente):
    ap = Aparelho.objects.create(modelo="iPhone 11")
    Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        aparelho=ap,
        valor_total=Decimal("1000.00"),
        estrutura=Contrato.Estrutura.MENSAL,
        data_inicio="2026-09-01",
    )
    resp = auth_client.post(reverse("aparelhos:excluir", args=[ap.pk]), follow=True)
    assert resp.status_code == 200
    assert Aparelho.objects.filter(pk=ap.pk).exists()  # não apagou
    assert "não pode ser excluído" in resp.content.decode()
