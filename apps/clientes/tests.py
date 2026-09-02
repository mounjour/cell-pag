import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato

CPF_VALIDO = CPFGen().generate()  # 11 dígitos, DV correto


def novo_cliente(**kwargs):
    dados = dict(nome="Fulano de Tal", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    dados.update(kwargs)
    c = Cliente(**dados)
    c.full_clean()
    c.save()
    return c


# ---------- Modelo ----------

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
    assert len(c.cpf) == 11 and c.cpf.isdigit()
    assert c.cpf_formatado == formatado


@pytest.mark.django_db
def test_telefone_exibicao_e_whatsapp_url():
    c = novo_cliente(telefone_whatsapp="83 98888-7777")
    assert c.telefone_exibicao == "(83) 98888-7777"
    assert c.whatsapp_url == "https://wa.me/5583988887777"


@pytest.mark.django_db
def test_detalhe_mostra_telefone_clicavel(auth_client):
    c = novo_cliente(nome="Zé", telefone_whatsapp="83 98888-7777")
    corpo = auth_client.get(reverse("clientes:detalhe", args=[c.pk])).content.decode()
    assert 'href="tel:+5583988887777"' in corpo
    assert "(83) 98888-7777" in corpo
    assert "https://wa.me/5583988887777" in corpo


# ---------- Telas ----------

@pytest.mark.django_db
def test_lista_exige_login(client):
    resp = client.get(reverse("clientes:lista"))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_cadastro_de_cliente_pela_tela(auth_client):
    resp = auth_client.post(
        reverse("clientes:novo"),
        {"nome": "Maria", "cpf": CPFGen().mask(CPF_VALIDO), "telefone_whatsapp": "83 99999-0000", "endereco": ""},
    )
    assert resp.status_code == 302
    assert Cliente.objects.filter(nome="Maria", cpf=CPF_VALIDO).exists()


@pytest.mark.django_db
def test_busca_filtra_por_nome_e_cpf(auth_client):
    a = novo_cliente(nome="Ana Souza")
    novo_cliente(nome="Bruno Lima")
    resp = auth_client.get(reverse("clientes:lista"), {"q": "ana"})
    nomes = {c.nome for c in resp.context["clientes"]}
    assert nomes == {"Ana Souza"}
    resp = auth_client.get(reverse("clientes:lista"), {"q": a.cpf[:5]})
    assert list(resp.context["clientes"]) == [a]


@pytest.mark.django_db
def test_detalhe_lista_contratos_do_cliente(auth_client):
    import datetime

    c = novo_cliente(nome="Carla")
    Contrato.objects.create(
        cliente=c, apelido="iPhone 12", aparelho_modelo="iPhone 12",
        valor_total="3000.00", estrutura=Contrato.Estrutura.MENSAL,
        data_inicio=datetime.date(2026, 8, 1),
    )
    resp = auth_client.get(reverse("clientes:detalhe", args=[c.pk]))
    assert resp.status_code == 200
    assert list(resp.context["contratos"])[0].apelido == "iPhone 12"


@pytest.mark.django_db
def test_editar_cliente(auth_client):
    c = novo_cliente(nome="Nome Velho")
    resp = auth_client.post(
        reverse("clientes:editar", args=[c.pk]),
        {"nome": "Nome Novo", "cpf": c.cpf, "telefone_whatsapp": "+5583999990000", "endereco": "Rua 1"},
    )
    assert resp.status_code == 302
    c.refresh_from_db()
    assert c.nome == "Nome Novo"
    assert c.endereco == "Rua 1"
