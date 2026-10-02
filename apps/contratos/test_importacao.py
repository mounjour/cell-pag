import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.contratos.importacao import chave_cliente, contar_por_cliente

CABECALHO = "cliente;contato;modelo;data da compra;frequencia de pagamento;parcela atual;total de parcelas;vencimento da parcela;valor da parcela"


def _linha(cliente, contato, modelo="iPhone 11"):
    return f"{cliente};{contato};{modelo};05/06/2026;diario;3;100;28/09/2026;20,00"


def test_mesmo_telefone_e_o_mesmo_cliente_mesmo_com_nome_escrito_diferente():
    a = {"cliente": "Douglas", "telefone": "88982351726"}
    b = {"cliente": " DOUGLAS  ", "telefone": "88982351726"}
    assert chave_cliente(a) == chave_cliente(b)


def test_nomes_iguais_com_telefones_diferentes_sao_pessoas_diferentes():
    a = {"cliente": "Gabriel", "telefone": "88993274602"}
    b = {"cliente": "Gabriel", "telefone": "88981385528"}
    assert chave_cliente(a) != chave_cliente(b)


def test_cpf_vale_mais_que_o_telefone():
    a = {"cliente": "Ana", "cpf": "11122233344", "telefone": "1"}
    b = {"cliente": "Ana", "cpf": "11122233344", "telefone": "2"}
    assert chave_cliente(a) == chave_cliente(b)


def test_contar_por_cliente_ignora_linhas_com_erro_e_marca_as_repetidas():
    linhas = [
        {"cliente": "Douglas", "telefone": "1"},
        {"cliente": "Douglas", "telefone": "1"},
        {"cliente": "Leo", "telefone": "2"},
        {"linha": 9, "erros": ["data inválida"]},
    ]
    clientes, validas = contar_por_cliente(linhas)
    assert (clientes, validas) == (2, 3)
    assert [l.get("contratos_do_cliente") for l in linhas] == [2, 2, 1, None]


@pytest.mark.django_db
def test_previa_mostra_mais_linhas_que_clientes(auth_client):
    csv = "\n".join(
        [
            CABECALHO,
            _linha("Douglas", "88982351726", "iPhone 11"),
            _linha("Douglas", "88982351726", "iPhone 14"),
            _linha("Leo", "88996243516"),
        ]
    )
    arquivo = SimpleUploadedFile("planilha.csv", csv.encode("utf-8"), content_type="text/csv")
    resposta = auth_client.post(reverse("contratos:importar_previa"), {"arquivo": arquivo})
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert "São 3 linhas para 2 clientes" in html
    assert "mesmo cliente de outras 1 linha" in html
