import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes import importacao
from apps.clientes.models import Cliente

pytestmark = pytest.mark.django_db


def _cpf_valido(*, com_zero=False):
    gerador = CPFGen()
    while True:
        cpf = gerador.generate()
        if cpf.startswith("0") == com_zero:
            return cpf


def _csv(*linhas, cabecalho="nome,cpf,telefone"):
    return ("\n".join([cabecalho, *linhas]) + "\n").encode("utf-8")


def test_linha_completa_e_valida_entra():
    cpf = _cpf_valido()
    linhas, erro = importacao.analisar(_csv(f"Maria Teste,{cpf},88992351726"))
    assert erro == ""
    assert linhas[0]["situacao"] == importacao.NOVO
    assert linhas[0]["cpf"] == cpf
    assert linhas[0]["telefone"] == "+5588992351726"


def test_cpf_que_perdeu_o_zero_e_completado_quando_fica_valido():
    cpf = _cpf_valido(com_zero=True)
    linhas, _ = importacao.analisar(_csv(f"Joao Zero,{cpf.lstrip('0')},88992351726"))
    assert linhas[0]["situacao"] == importacao.NOVO
    assert linhas[0]["cpf"] == cpf


def test_cpf_incompleto_ou_invalido_fica_de_fora():
    valido = _cpf_valido()
    invalido = valido[:-1] + str((int(valido[-1]) + 1) % 10)
    linhas, _ = importacao.analisar(_csv(
        f"Curto,{valido[:8]},88992351726",
        f"Invalido,{invalido},88992351726",
        "SemCpf,,88992351726",
    ))
    assert [l["situacao"] for l in linhas] == [importacao.REJEITADO] * 3
    assert "incompleto" in linhas[0]["motivo"].lower()
    assert "inválido" in linhas[1]["motivo"].lower()
    assert "ausente" in linhas[2]["motivo"].lower()


def test_sem_telefone_ou_telefone_invalido_fica_de_fora():
    cpf1, cpf2 = _cpf_valido(), _cpf_valido()
    linhas, _ = importacao.analisar(_csv(f"Sem Tel,{cpf1},", f"Tel Ruim,{cpf2},123"))
    assert [l["situacao"] for l in linhas] == [importacao.REJEITADO] * 2
    assert "telefone" in linhas[0]["motivo"].lower()


def test_cpf_ja_cadastrado_e_repetido_no_arquivo_ficam_de_fora():
    existente, novo = _cpf_valido(), _cpf_valido()
    Cliente.objects.create(nome="Ja Existe", cpf=existente, telefone_whatsapp="+5588992351726")
    linhas, _ = importacao.analisar(_csv(
        f"Ja Existe 2,{existente},88992351726",
        f"Novo,{novo},88992351726",
        f"Novo Repetido,{novo},88992351726",
    ))
    assert [l["situacao"] for l in linhas] == [importacao.JA_CADASTRADO, importacao.NOVO, importacao.REPETIDO]


def test_aceita_ponto_e_virgula_e_cabecalhos_alternativos():
    cpf = _cpf_valido()
    conteudo = _csv(f"Ana;{cpf};(88) 99235-1726", cabecalho="Cliente;CPF;Contato").replace(b",", b";")
    linhas, erro = importacao.analisar(conteudo)
    assert erro == "" and linhas[0]["situacao"] == importacao.NOVO


def test_colunas_obrigatorias_ausentes():
    linhas, erro = importacao.analisar(_csv("Fulano,123", cabecalho="nome,cpf"))
    assert linhas == [] and "telefone" in erro


def test_gravar_cria_so_as_linhas_novas():
    cpf = _cpf_valido()
    linhas, _ = importacao.analisar(_csv(f"Cria,{cpf},88992351726", "Sem Cpf,,88992351726"))
    assert importacao.gravar(linhas) == 1
    cliente = Cliente.objects.get(cpf=cpf)
    assert cliente.nome == "Cria" and not cliente.contratos.exists()


def test_importar_exige_login(client):
    assert client.get(reverse("clientes:importar")).status_code == 302
    assert client.post(reverse("clientes:importar_confirmar")).status_code == 302


def test_fluxo_previa_e_confirmacao(auth_client):
    cpf = _cpf_valido()
    arquivo = SimpleUploadedFile("clientes.csv", _csv(f"Via Tela,{cpf},88992351726", "Sem Cpf,,88992351726"))
    previa = auth_client.post(reverse("clientes:importar"), {"arquivo": arquivo})
    assert previa.status_code == 200
    assert previa.context["resumo"]["novos"] == 1 and previa.context["resumo"]["de_fora"] == 1
    assert not Cliente.objects.exists()  # a prévia não grava nada

    resposta = auth_client.post(reverse("clientes:importar_confirmar"))
    assert resposta.status_code == 302
    assert Cliente.objects.filter(cpf=cpf).exists() and Cliente.objects.count() == 1


def test_confirmar_sem_previa_nao_cria_nada(auth_client):
    resposta = auth_client.post(reverse("clientes:importar_confirmar"))
    assert resposta.status_code == 302 and not Cliente.objects.exists()


def test_so_aceita_arquivo_csv(auth_client):
    arquivo = SimpleUploadedFile("clientes.xlsx", b"x")
    resposta = auth_client.post(reverse("clientes:importar"), {"arquivo": arquivo})
    assert resposta.status_code == 200 and "arquivo" in resposta.context["form"].errors
