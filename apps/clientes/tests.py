import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente

CPF_VALIDO = CPFGen().generate()  # 11 dígitos, DV correto


def novo_cliente(**kwargs):
    dados = dict(nome="Fulano de Tal", cpf=CPF_VALIDO, telefone_whatsapp="+5583999990000")
    dados.update(kwargs)
    c = Cliente(**dados)
    c.full_clean()
    c.save()
    return c


@pytest.mark.django_db
def test_cpf_invalido_rejeitado():
    c = Cliente(nome="X", cpf="12345678900", telefone_whatsapp="+5583999990000")
    with pytest.raises(ValidationError):
        c.full_clean()


@pytest.mark.django_db
def test_cpf_normalizado_para_digitos():
    formatado = CPFGen().mask(CPF_VALIDO)  # 000.000.000-00
    c = novo_cliente(cpf=formatado)
    assert c.cpf == CPF_VALIDO
    assert c.cpf_formatado == formatado


@pytest.mark.django_db
def test_lista_exige_login(client):
    resp = client.get(reverse("clientes:lista"))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_cadastro_de_cliente_pela_tela(client, django_user_model):
    django_user_model.objects.create_user("op", password="s3nha-forte-123")
    client.login(username="op", password="s3nha-forte-123")
    resp = client.post(
        reverse("clientes:novo"),
        {"nome": "Maria", "cpf": CPFGen().mask(CPF_VALIDO), "telefone_whatsapp": "83 99999-0000", "endereco": ""},
    )
    assert resp.status_code == 302
    assert Cliente.objects.filter(nome="Maria", cpf=CPF_VALIDO).exists()
