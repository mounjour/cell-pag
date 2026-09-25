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
    # O link é só o telefone (mesmo número do WhatsApp) — decisão do Alisson
    # (14/09): sem link/texto "WhatsApp" separado no detalhe do cliente.
    c = novo_cliente(nome="Zé", telefone_whatsapp="83 98888-7777")
    corpo = auth_client.get(reverse("clientes:detalhe", args=[c.pk])).content.decode()
    assert 'href="tel:+5583988887777"' in corpo
    assert "(83) 98888-7777" in corpo


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


# ---------- Arquivar / reativar / excluir ----------

def _contrato_quitado(cliente):
    import datetime

    return Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11",
        valor_total="400.00",
        estrutura=Contrato.Estrutura.MENSAL,
        data_inicio=datetime.date(2026, 1, 1),
        status=Contrato.Status.QUITADO,
    )


@pytest.mark.django_db
def test_cliente_novo_comeca_ativo():
    c = novo_cliente()
    assert c.ativo is True


@pytest.mark.django_db
def test_lista_esconde_arquivados_por_padrao(auth_client):
    ativo = novo_cliente(nome="Ativa")
    arquivado = novo_cliente(nome="Arquivada", ativo=False)
    nomes = {c.nome for c in auth_client.get(reverse("clientes:lista")).context["clientes"]}
    assert nomes == {"Ativa"}
    nomes_arquivados = {
        c.nome for c in auth_client.get(reverse("clientes:lista"), {"arquivados": "1"}).context["clientes"]
    }
    assert nomes_arquivados == {"Arquivada"}


@pytest.mark.django_db
def test_arquivar_e_reativar_cliente(auth_client):
    c = novo_cliente()
    resp = auth_client.post(reverse("clientes:arquivar", args=[c.pk]), follow=True)
    c.refresh_from_db()
    assert c.ativo is False
    assert "arquivado" in resp.content.decode().lower()

    resp = auth_client.post(reverse("clientes:reativar", args=[c.pk]), follow=True)
    c.refresh_from_db()
    assert c.ativo is True
    assert "reativado" in resp.content.decode().lower()


@pytest.mark.django_db
def test_excluir_cliente_sem_contrato_funciona(auth_client):
    c = novo_cliente()
    assert c.pode_ser_excluido is True
    auth_client.post(reverse("clientes:excluir", args=[c.pk]))
    assert not Cliente.objects.filter(pk=c.pk).exists()


@pytest.mark.django_db
def test_excluir_cliente_com_contrato_e_recusado(auth_client):
    c = novo_cliente()
    _contrato_quitado(c)
    assert c.pode_ser_excluido is False
    resp = auth_client.post(reverse("clientes:excluir", args=[c.pk]), follow=True)
    assert Cliente.objects.filter(pk=c.pk).exists()
    assert "Arquivar" in resp.content.decode()


@pytest.mark.django_db
def test_todos_contratos_quitados_mostra_aviso_para_arquivar(auth_client):
    c = novo_cliente()
    _contrato_quitado(c)
    assert c.todos_contratos_quitados is True
    corpo = auth_client.get(reverse("clientes:detalhe", args=[c.pk])).content.decode()
    assert "estão quitados" in corpo
    assert reverse("clientes:arquivar", args=[c.pk]) in corpo


@pytest.mark.django_db
def test_sem_contrato_nenhum_mostra_aviso_de_excluir(auth_client):
    c = novo_cliente()
    assert c.todos_contratos_quitados is False  # sem contrato nenhum não conta
    corpo = auth_client.get(reverse("clientes:detalhe", args=[c.pk])).content.decode()
    assert reverse("clientes:excluir", args=[c.pk]) in corpo
