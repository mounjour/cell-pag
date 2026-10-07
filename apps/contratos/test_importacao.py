import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.contratos.importacao import chave_cliente, contar_por_cliente

CABECALHO = "cliente;contato;modelo;data da compra;frequencia de pagamento;parcela atual;total de parcelas;vencimento da parcela;valor da parcela"


def _linha(cliente, contato, modelo="iPhone 11"):
    return f"{cliente};{contato};{modelo};05/06/2026;semanal;3;100;28/09/2026;20,00"


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


@pytest.mark.parametrize("removida", ["diario", "Diário", "por dezena"])
def test_frequencia_que_saiu_e_recusada_com_motivo_claro(removida):
    from apps.contratos.importacao import analisar

    conteudo = CABECALHO + "\nAna;88999990000;iPhone 11;05/06/2026;" + removida + ";3;100;28/09/2026;20,00"
    linhas, avisos = analisar(SimpleUploadedFile("c.csv", conteudo.encode("utf-8-sig")))
    assert linhas[0]["erros"] == ["Frequência não aceita: o sistema trabalha só com semanal, quinzenal e mensal."]


# ---------- IMEI da planilha → aparelho no estoque ----------

def _analisar(*linhas, cabecalho="cliente;contato;modelo;emei;data da compra;frequencia de pagamento;parcela atual;total de parcelas;vencimento da parcela;valor da parcela"):
    from apps.contratos.importacao import analisar

    conteudo = "\n".join([cabecalho, *linhas])
    return analisar(SimpleUploadedFile("c.csv", conteudo.encode("utf-8-sig")))[0]


def test_importacao_le_o_imei_pela_coluna_emei_ou_imei():
    linha = "Ana;88999990000;iPhone 11;351166892953468;05/06/2026;semanal;0;10;28/09/2026;100,00"
    assert _analisar(linha)[0]["imei"] == "351166892953468"
    cab = "cliente;contato;modelo;imei;data da compra;frequencia de pagamento;parcela atual;total de parcelas;vencimento da parcela;valor da parcela"
    assert _analisar(linha, cabecalho=cab)[0]["imei"] == "351166892953468"


@pytest.mark.parametrize("bruto, trecho", [
    ("", "IMEI ausente"), ("----", "IMEI ausente"), ("12345", "IMEI inválido"),
])
def test_imei_ausente_ou_invalido_vira_alerta_e_fica_sem_vinculo(bruto, trecho):
    linha = f"Ana;88999990000;iPhone 11;{bruto};05/06/2026;semanal;0;10;28/09/2026;100,00"
    resultado = _analisar(linha)[0]
    assert resultado["imei"] == ""
    assert any(trecho in alerta for alerta in resultado["alertas"])


def _pendencia(imei, **extra):
    from apps.contratos.models import ImportacaoContratoPendente

    dados = {"linha": 2, "cliente": "Ana Importada", "modelo": "iPhone 11", "imei": imei, "estrutura": "semanal",
             "inicio": "2026-09-01", "vencimento": "2026-09-08", "parcelas": 10, "valor": "100.00", "juros": "5.00",
             "observacoes": "", **extra}
    return ImportacaoContratoPendente.objects.create(dados=dados, problemas=[], linha_origem=2)


def _resolver(auth_client, pendencia, cpf):
    return auth_client.post(reverse("contratos:resolver_importacao", args=[pendencia.pk]), {
        "cpf": cpf, "telefone": "88999990000", "valor_total": "1000,00", "parcelas_ja_pagas": "0"})


@pytest.mark.django_db
def test_resolver_cria_o_aparelho_no_estoque_e_vincula_ao_contrato(auth_client):
    from validate_docbr import CPF

    from apps.aparelhos.models import Aparelho
    from apps.contratos.models import Contrato

    resp = _resolver(auth_client, _pendencia("351166892953468"), CPF().generate())
    assert resp.status_code == 302
    contrato = Contrato.objects.get()
    aparelho = Aparelho.objects.get(imei="351166892953468")
    assert (contrato.aparelho_id, contrato.imei) == (aparelho.pk, "351166892953468")
    assert aparelho.modelo == "iPhone 11" and aparelho.status == Aparelho.Status.ALOCADO


@pytest.mark.django_db
def test_resolver_reaproveita_aparelho_livre_do_estoque(auth_client):
    from validate_docbr import CPF

    from apps.aparelhos.models import Aparelho
    from apps.contratos.models import Contrato

    existente = Aparelho.objects.create(modelo="iPhone 11 64GB", imei="351166892953468")
    _resolver(auth_client, _pendencia("351166892953468"), CPF().generate())
    assert Aparelho.objects.count() == 1
    assert Contrato.objects.get().aparelho_id == existente.pk


@pytest.mark.django_db
def test_resolver_recusa_imei_que_ja_pertence_a_outro_contrato(auth_client):
    from validate_docbr import CPF

    from apps.contratos.models import Contrato

    _resolver(auth_client, _pendencia("351166892953468"), CPF().generate())
    segunda = _pendencia("351166892953468")
    resp = _resolver(auth_client, segunda, CPF().generate())
    assert resp.status_code == 200
    assert "já pertence a um aparelho com contrato" in resp.content.decode()
    assert Contrato.objects.count() == 1
    segunda.refresh_from_db()
    assert segunda.resolvida_em is None


@pytest.mark.django_db
def test_resolver_sem_imei_cria_contrato_sem_vinculo(auth_client):
    from validate_docbr import CPF

    from apps.aparelhos.models import Aparelho
    from apps.contratos.models import Contrato

    _resolver(auth_client, _pendencia(""), CPF().generate())
    assert Contrato.objects.get().aparelho_id is None
    assert not Aparelho.objects.exists()
