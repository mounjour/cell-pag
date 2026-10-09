"""Dia de cobrança no cadastro, na prévia e na importação de contratos."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from validate_docbr import CPF

from apps.contratos import importacao
from apps.contratos.forms import ContratoForm
from apps.contratos.models import Contrato, ImportacaoContratoPendente
from apps.contratos.tests import cliente, dados_form, novo_contrato  # noqa: F401  (cliente é fixture)

pytestmark = pytest.mark.django_db


def _form(cliente, **over):
    dados = dados_form(cliente, **over)
    dados.pop("dia_mes", None) if "dia_mes" not in over else None
    return ContratoForm(dados)


def test_cadastro_novo_exige_o_dia_de_cobranca(cliente):
    form = _form(cliente, estrutura="semanal")
    assert not form.is_valid()
    assert "Escolha o dia da semana" in str(form.errors["dia_semana"])


def test_dia_da_semana_gera_a_primeira_cobranca_sugerida(cliente):
    form = _form(cliente, estrutura="semanal", data_inicio="2026-09-25", dia_semana="4")  # sexta
    assert form.is_valid(), form.errors
    contrato = form.save()
    assert contrato.primeira_cobranca == datetime.date(2026, 10, 2)
    assert contrato.dia_de_cobranca == "Toda sexta-feira"
    assert contrato.data_da_parcela(2) == datetime.date(2026, 10, 9)


def test_primeira_cobranca_editada_vale_e_o_dia_segue_a_data(cliente):
    form = _form(cliente, estrutura="semanal", data_inicio="2026-09-17", dia_semana="1",
                 primeira_cobranca="2026-11-03")  # terça (exceção combinada com o cliente)
    assert form.is_valid(), form.errors
    contrato = form.save()
    assert contrato.primeira_cobranca == datetime.date(2026, 11, 3)
    assert contrato.data_da_parcela(2) == datetime.date(2026, 11, 10)


def test_dia_da_semana_diferente_da_data_e_recusado(cliente):
    form = _form(cliente, estrutura="semanal", data_inicio="2026-09-17", dia_semana="0", primeira_cobranca="2026-11-03")
    assert not form.is_valid()
    assert "terça-feira" in str(form.errors["primeira_cobranca"])


def test_quinzenal_em_dois_dias_do_mes_grava_os_dias(cliente):
    form = _form(cliente, estrutura="quinzenal", quinzena="dias_mes", dia_mes="5", dia_mes_2="20", data_inicio="2026-07-22")
    assert form.is_valid(), form.errors
    contrato = form.save()
    assert contrato.dias_cobranca_mes == "5,20"
    assert contrato.primeira_cobranca == datetime.date(2026, 8, 20)
    assert [contrato.data_da_parcela(n) for n in (2, 3)] == [datetime.date(2026, 9, 5), datetime.date(2026, 9, 20)]


def test_quinzenal_a_cada_14_dias_no_mesmo_dia_da_semana(cliente):
    form = _form(cliente, estrutura="quinzenal", quinzena="semana", dia_semana="2", data_inicio="2026-09-23")
    assert form.is_valid(), form.errors
    contrato = form.save()
    assert contrato.dias_cobranca_mes == ""
    assert contrato.primeira_cobranca.weekday() == 2
    assert (contrato.data_da_parcela(2) - contrato.data_da_parcela(1)).days == 14


def test_mensal_guarda_o_dia_e_cai_no_ultimo_dia_do_mes_curto(cliente):
    form = _form(cliente, estrutura="mensal", dia_mes="31", data_inicio="2026-01-05")
    assert form.is_valid(), form.errors
    contrato = form.save()
    assert contrato.dias_cobranca_mes == "31"
    assert contrato.primeira_cobranca == datetime.date(2026, 2, 28)
    assert contrato.data_da_parcela(2) == datetime.date(2026, 3, 31)


def test_editar_contrato_antigo_sem_dia_de_cobranca_nao_muda_o_calendario(cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.QUINZENAL, data_inicio=datetime.date(2026, 8, 1))
    ct.refresh_from_db()
    antes = ct.data_da_parcela(2)
    dados = dados_form(cliente, apelido="Renomeado", estrutura="quinzenal", aparelho="",
                       aparelho_modelo="iPhone 11", imei="359999053372501", data_inicio="2026-08-01")
    dados.pop("dia_mes")
    form = ContratoForm(dados, instance=ct)
    assert form.is_valid(), form.errors
    ct = form.save()
    assert ct.primeira_cobranca is None and ct.data_da_parcela(2) == antes  # segue contando de 15 em 15


def test_previa_ao_vivo_mostra_o_dia_de_cobranca_e_as_datas(auth_client, cliente):
    resposta = auth_client.post(reverse("contratos:previsao"), {
        "valor_total": "1000,00", "num_parcelas": "10", "estrutura": "semanal", "data_inicio": "2026-09-25",
        "dia_semana": "4", "juros_diario": "5,00", "parcelas_ja_pagas": "0", "entrada": "", "cliente": cliente.pk,
    }).json()
    assert "toda sexta-feira" in resposta["texto"]
    assert "Primeira cobrança: 02/10/2026" in resposta["texto"]


def test_previa_ao_vivo_explica_o_que_falta_escolher(auth_client, cliente):
    resposta = auth_client.post(reverse("contratos:previsao"), {
        "valor_total": "1000,00", "num_parcelas": "10", "estrutura": "semanal", "data_inicio": "2026-09-25",
    }).json()
    assert "dia da semana" in resposta["texto"]


# ── importação ─────────────────────────────────────────────────────────────

CABECALHO = ("cliente;contato;cpf;modelo;imei;data da compra;frequência de pagamento;parcela atual;"
             "total de parcelas;vencimento da parcela;valor da parcela;juros diário;observações")


def _analisar(*linhas):
    conteudo = "\n".join([CABECALHO, *linhas]).encode("utf-8")
    resultado, erros = importacao.analisar(SimpleUploadedFile("p.csv", conteudo, content_type="text/csv"))
    assert not erros
    return resultado


def test_importacao_mensal_usa_o_dia_do_vencimento_e_avisa_quando_o_nome_da_planilha_diverge():
    linha = _analisar("Felicia;88921448741;;iPhone 13;;29/07/2026;Mensal - 30;1;10;01/10/2026;300,00;5,00;")[0]
    assert linha["dias_mes"] == "1"
    assert any("Mensal - 30" in aviso and "dia 1" in aviso for aviso in linha["alertas"])


def test_importacao_quinzenal_com_dois_dias_nas_observacoes():
    linha = _analisar("Miguel;88996742785;;iPhone 13;;22/07/2026;Quinzenal;5;10;20/10/2026;310,00;5,00;Dia 5 e 20")[0]
    assert linha["dias_mes"] == "5,20" and linha["parcela_atual"] == 5


def test_importacao_semanal_e_quinzenal_por_dia_da_semana_nao_guardam_dias_do_mes():
    semanal, quinzenal = _analisar(
        "Alef;88981406068;;iPhone 14;;26/08/2026;Semanal;2;90;05/10/2026;87,50;5,00;Cobrar na Segunda",
        "Debora;88996615303;;iPhone 13;;23/09/2026;Quinzenal;0;20;07/10/2026;175,00;5,00;Cobrar na Quarta",
    )
    assert semanal["dias_mes"] == "" and quinzenal["dias_mes"] == ""


def _pendencia(**extra):
    dados = {"linha": 2, "cliente": "Ana Importada", "modelo": "iPhone 11", "imei": "", "estrutura": "semanal",
             "inicio": "2026-08-26", "vencimento": "2026-10-05", "parcelas": 90, "valor": "87.50", "juros": "5.00",
             "observacoes": "", **extra}
    return ImportacaoContratoPendente.objects.create(dados=dados, problemas=[], linha_origem=2)


def _resolver(auth_client, pendencia, pagas):
    return auth_client.post(reverse("contratos:resolver_importacao", args=[pendencia.pk]), {
        "cpf": CPF().generate(), "telefone": "88999990000", "valor_total": "7875,00", "parcelas_ja_pagas": str(pagas)})


@pytest.mark.parametrize("estrutura, dias, vencimento, pagas", [
    ("semanal", "", "2026-10-05", 2),
    ("quinzenal", "", "2026-10-07", 3),
    ("quinzenal", "5,20", "2026-10-20", 5),
    ("mensal", "15", "2026-10-15", 4),
])
def test_resolver_monta_o_calendario_de_modo_que_a_proxima_parcela_cai_no_vencimento_da_planilha(
        auth_client, estrutura, dias, vencimento, pagas):
    resp = _resolver(auth_client, _pendencia(estrutura=estrutura, dias_mes=dias, vencimento=vencimento, parcela_atual=pagas), pagas)
    assert resp.status_code == 302
    contrato = Contrato.objects.get()
    assert contrato.dias_cobranca_mes == dias
    assert contrato.data_da_parcela(pagas + 1) == datetime.date.fromisoformat(vencimento)
    assert contrato.data_inicio == datetime.date(2026, 8, 26)  # data da compra como veio


def test_tela_de_resolver_ja_vem_com_as_parcelas_pagas_da_planilha(auth_client):
    pendencia = _pendencia(parcela_atual=2)
    html = auth_client.get(reverse("contratos:resolver_importacao", args=[pendencia.pk])).content.decode()
    assert 'name="parcelas_ja_pagas"' in html and 'value="2"' in html
