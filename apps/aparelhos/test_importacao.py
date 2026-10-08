import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.aparelhos import importacao
from apps.aparelhos.models import Aparelho

pytestmark = pytest.mark.django_db

IMEI = "357397702449116"
OUTRO_IMEI = "357712765289300"


def _csv(*linhas, cabecalho="modelo;imei"):
    return ("\n".join([cabecalho, *linhas]) + "\n").encode("utf-8")


def test_linha_valida_entra_e_modelo_usa_grafia_do_catalogo():
    linhas, erro = importacao.analisar(_csv(f"  iphone 14   pro max ;{IMEI}"))
    assert erro == ""
    assert linhas[0]["situacao"] == importacao.NOVO
    assert linhas[0]["modelo"] == "iPhone 14 Pro Max"
    assert linhas[0]["imei"] == IMEI


def test_modelo_fora_do_catalogo_e_aceito_como_digitado():
    linhas, _ = importacao.analisar(_csv(f"iPhone XR;{IMEI}"))
    assert linhas[0]["situacao"] == importacao.NOVO and linhas[0]["modelo"] == "iPhone XR"


def test_imei_ausente_curto_longo_e_cientifico_ficam_de_fora():
    linhas, _ = importacao.analisar(_csv("iPhone 13;", "iPhone 13;12345", f"iPhone 13;{IMEI}9", "iPhone 13;3,57E+14"))
    assert [l["situacao"] for l in linhas] == [importacao.REJEITADO] * 4
    assert "ausente" in linhas[0]["motivo"]
    assert "15 dígitos" in linhas[1]["motivo"] and "15 dígitos" in linhas[2]["motivo"]
    assert "científica" in linhas[3]["motivo"]


def test_sem_modelo_fica_de_fora():
    linhas, _ = importacao.analisar(_csv(f";{IMEI}"))
    assert linhas[0]["situacao"] == importacao.REJEITADO and "Modelo ausente" in linhas[0]["motivo"]


def test_imei_ja_cadastrado_e_repetido_no_arquivo_ficam_de_fora():
    Aparelho.objects.create(modelo="iPhone 13", imei=IMEI)
    linhas, _ = importacao.analisar(_csv(f"iPhone 13;{IMEI}", f"iPhone 14;{OUTRO_IMEI}", f"iPhone 14;{OUTRO_IMEI}"))
    assert [l["situacao"] for l in linhas] == [importacao.JA_CADASTRADO, importacao.NOVO, importacao.REPETIDO]


def test_campos_opcionais_custo_data_e_fornecedor():
    linhas, _ = importacao.analisar(_csv(
        f"iPhone 13;{IMEI};R$ 1.250,50;Fornecedor X;05/10/2026;Caixa lacrada",
        cabecalho="modelo;imei;custo;fornecedor;data da compra;observações",
    ))
    assert linhas[0]["situacao"] == importacao.NOVO
    assert importacao.gravar(linhas) == 1
    aparelho = Aparelho.objects.get(imei=IMEI)
    assert aparelho.custo == Decimal("1250.50") and aparelho.fornecedor == "Fornecedor X"
    assert aparelho.data_compra == datetime.date(2026, 10, 5) and aparelho.observacoes == "Caixa lacrada"


def test_custo_ou_data_invalidos_ficam_de_fora():
    linhas, _ = importacao.analisar(_csv(
        f"iPhone 13;{IMEI};abc;;", f"iPhone 13;{OUTRO_IMEI};;;31/02/2026",
        cabecalho="modelo;imei;custo;fornecedor;data da compra",
    ))
    assert [l["situacao"] for l in linhas] == [importacao.REJEITADO] * 2
    assert "Custo inválido" in linhas[0]["motivo"] and "Data da compra inválida" in linhas[1]["motivo"]


def test_aceita_virgula_e_cabecalhos_alternativos():
    linhas, _ = importacao.analisar(_csv(f"iPhone 13,{IMEI}", cabecalho="Aparelho,EMEI"))
    assert linhas[0]["situacao"] == importacao.NOVO


def test_colunas_obrigatorias_ausentes():
    linhas, erro = importacao.analisar(_csv("iPhone 13", cabecalho="modelo"))
    assert linhas == [] and "imei" in erro


def test_gravar_cria_so_as_linhas_novas_sem_contrato():
    linhas, _ = importacao.analisar(_csv(f"iPhone 13;{IMEI}", "iPhone 13;123"))
    assert importacao.gravar(linhas) == 1
    aparelho = Aparelho.objects.get(imei=IMEI)
    assert aparelho.status == Aparelho.Status.DISPONIVEL and not aparelho.com_contrato


def test_importar_exige_login(client):
    assert client.get(reverse("aparelhos:importar")).status_code == 302
    assert client.post(reverse("aparelhos:importar_confirmar")).status_code == 302


def test_fluxo_previa_e_confirmacao(auth_client):
    arquivo = SimpleUploadedFile("aparelhos.csv", _csv(f"iPhone 13;{IMEI}", "iPhone 13;123"))
    previa = auth_client.post(reverse("aparelhos:importar"), {"arquivo": arquivo})
    assert previa.status_code == 200
    assert previa.context["resumo"]["novos"] == 1 and previa.context["resumo"]["de_fora"] == 1
    assert not Aparelho.objects.exists()  # a prévia não grava nada

    resposta = auth_client.post(reverse("aparelhos:importar_confirmar"))
    assert resposta.status_code == 302
    assert Aparelho.objects.filter(imei=IMEI).exists() and Aparelho.objects.count() == 1


def test_confirmar_sem_previa_nao_cria_nada(auth_client):
    resposta = auth_client.post(reverse("aparelhos:importar_confirmar"))
    assert resposta.status_code == 302 and not Aparelho.objects.exists()


def test_so_aceita_arquivo_csv(auth_client):
    arquivo = SimpleUploadedFile("aparelhos.xlsx", b"x")
    resposta = auth_client.post(reverse("aparelhos:importar"), {"arquivo": arquivo})
    assert resposta.status_code == 200 and "arquivo" in resposta.context["form"].errors


def test_botao_na_lista_de_aparelhos(auth_client):
    html = auth_client.get(reverse("aparelhos:lista")).content.decode()
    assert reverse("aparelhos:importar") in html
