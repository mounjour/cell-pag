import datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from validate_docbr import CPF

from apps.aparelhos.models import Aparelho
from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import Cobranca, CobrancaCora, Pagamento, Vencimento


@pytest.fixture
def cadastro(db):
    cliente = Cliente.objects.create(
        nome="Maria Teste", cpf=CPF().generate(), telefone_whatsapp="+5583999990000",
    )
    aparelho = Aparelho.objects.create(modelo="iPhone 13 128GB")
    return {
        "cliente": cliente.pk, "aparelho": aparelho.pk, "apelido": "iPhone da Maria",
        "aparelho_modelo": "iPhone 13 128GB", "imei": "359999053372501", "valor_total": "1000,00",
        "num_parcelas": "10", "estrutura": "diaria",
        "juros_diario": "5,00", "data_inicio": "2026-09-01", "status": "em_dia",
        "entrada": "200,00", "entrada_forma": "dinheiro", "parcelas_ja_pagas": "2",
    }


def confirmar(client, resposta, **extras):
    return client.post(reverse("contratos:novo"), {
        "revisao": resposta.context["revisao"], "acao": "confirmar", "conferido": "1",
        **extras,
    })


@pytest.mark.django_db
def test_revisao_nao_libera_rotina_nem_reserva_estoque(auth_client, cadastro):
    resposta = auth_client.post(reverse("contratos:novo"), cadastro)
    assert resposta.status_code == 200
    texto = resposta.content.decode()
    assert "Confirmar e iniciar cobrança" in texto
    assert "Maria Teste" in texto and "iPhone 13 128GB" in texto
    assert "04/09/2026" in texto  # primeira parcela não paga
    call_command("gerar_vencimentos", stdout=StringIO())
    from apps.pagamentos.cobranca import processar_cobrancas
    processar_cobrancas(hoje=datetime.date(2026, 10, 2))
    assert not Contrato.objects.exists()
    assert not Vencimento.objects.exists()
    assert not Pagamento.objects.exists()
    assert not Cobranca.objects.exists()
    assert not CobrancaCora.objects.exists()
    assert not Aparelho.objects.get(pk=cadastro["aparelho"]).com_contrato


@pytest.mark.django_db
def test_confirma_uma_vez_e_preserva_entrada_e_parcelas_pagas(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    assert confirmar(auth_client, resumo).status_code == 302
    assert confirmar(auth_client, resumo).status_code == 302
    contrato = Contrato.objects.get()
    assert contrato.vencimentos.count() == 10
    assert contrato.vencimentos.filter(status=Vencimento.Status.PAGO).count() == 2
    assert contrato.pagamentos.filter(vencimento__isnull=True).get().valor_pago == Decimal("200.00")
    assert contrato.pagamentos.count() == 3
    assert contrato.aparelho.alocado
    from apps.pagamentos.agenda import montar_agenda_do_dia
    agenda = montar_agenda_do_dia(hoje=datetime.date(2026, 10, 2))
    assert len(agenda["linhas"]) == 1
    assert agenda["linhas"][0]["parcelas"][0].numero == 3


@pytest.mark.django_db
def test_corrigir_preserva_formulario_sem_salvar(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    resposta = confirmar(auth_client, resumo, acao="corrigir", conferido="")
    assert resposta.context["form"]["entrada"].value() == "200,00"
    assert resposta.context["form"]["parcelas_ja_pagas"].value() == "2"
    assert not Contrato.objects.exists()
    cadastro["valor_total"] = "900,00"
    novo = auth_client.post(reverse("contratos:novo"), cadastro)
    assert "90,00" in novo.content.decode()  # 900 ÷ 10 parcelas, calculado sozinho


@pytest.mark.django_db
def test_dados_cliente_alterados_exigem_nova_revisao(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    Cliente.objects.filter(pk=cadastro["cliente"]).update(nome="Nome corrigido")
    resposta = confirmar(auth_client, resumo)
    assert resposta.status_code == 200
    assert "Nome corrigido" in resposta.content.decode()
    assert not Contrato.objects.exists()
    assert confirmar(auth_client, resposta).status_code == 302


@pytest.mark.django_db
def test_confirmacao_sem_checkbox_ou_sem_resumo_nao_salva(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), {**cadastro, "acao": "confirmar", "conferido": "1"})
    assert not Contrato.objects.exists()
    resposta = confirmar(auth_client, resumo, conferido="")
    assert resposta.status_code == 200
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_resumo_alterado_recusado(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    resposta = confirmar(auth_client, resumo, revisao=resumo.context["revisao"] + "x")
    assert resposta.status_code == 302
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_resumo_expirado_recusado(auth_client, cadastro, monkeypatch):
    from django.core import signing
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    agora = signing.time.time()
    monkeypatch.setattr(signing.time, "time", lambda: agora + 3601)
    assert confirmar(auth_client, resumo).status_code == 302
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_resumo_de_outro_operador_recusado(auth_client, cadastro, django_user_model):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    outro = django_user_model.objects.create_user("outro-operador")
    auth_client.force_login(outro)
    assert confirmar(auth_client, resumo).status_code == 302
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_confirmacao_repetida_em_outra_sessao_nao_duplica(auth_client, cadastro, operador):
    from django.test import Client
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    assert confirmar(auth_client, resumo).status_code == 302
    outra_sessao = Client()
    outra_sessao.force_login(operador)
    assert confirmar(outra_sessao, resumo).status_code == 302
    assert Contrato.objects.count() == 1


@pytest.mark.django_db
def test_revalida_estoque_na_confirmacao(auth_client, cadastro):
    resumo = auth_client.post(reverse("contratos:novo"), cadastro)
    Contrato.objects.create(
        cliente_id=cadastro["cliente"], aparelho_id=cadastro["aparelho"],
        apelido="Outra venda", aparelho_modelo="iPhone 13", valor_total=1000,
        estrutura="diaria", data_inicio=datetime.date(2026, 9, 1),
    )
    resposta = confirmar(auth_client, resumo)
    assert resposta.status_code == 200
    assert "aparelho" in resposta.context["form"].errors
    assert Contrato.objects.count() == 1


@pytest.mark.django_db
def test_pagas_nao_podem_exceder_quantidade_calculada(auth_client, cadastro):
    resposta = auth_client.post(reverse("contratos:novo"), {
        **cadastro, "parcelas_ja_pagas": "11",
    })
    assert "parcelas_ja_pagas" in resposta.context["form"].errors
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_catalogo_nos_dois_formularios_so_permite_escolher(auth_client):
    for nome in ("aparelhos:novo", "contratos:novo"):
        resposta = auth_client.get(reverse(nome))
        texto = resposta.content.decode()
        assert "<select" in texto
        assert "<datalist" not in texto
        assert 'value="iPhone 13 Pro Max"' in texto
        assert 'value="iPhone 18 Pro"' in texto
        assert 'value="iPhone 11"' in texto
        assert 'value="iPhone X"' not in texto
        assert 'value="iPhone 8"' not in texto
        assert 'value="iPhone SE (3ª geração)"' not in texto


@pytest.mark.django_db
def test_modelo_fora_da_lista_e_recusado(auth_client, cadastro):
    resposta = auth_client.post(reverse("contratos:novo"), {**cadastro, "aparelho_modelo": "Modelo inventado"})
    assert "aparelho_modelo" in resposta.context["form"].errors
    assert not Contrato.objects.exists()
    from apps.aparelhos.forms import AparelhoForm
    form = AparelhoForm(data={"modelo": "Modelo inventado"})
    assert not form.is_valid()
    assert "modelo" in form.errors


@pytest.mark.django_db
def test_edicao_preserva_modelo_antigo_com_capacidade(auth_client):
    aparelho = Aparelho.objects.create(modelo="iPhone 11 64GB")
    resposta = auth_client.get(reverse("aparelhos:editar", args=[aparelho.pk]))
    assert 'value="iPhone 11 64GB" selected' in resposta.content.decode()


@pytest.mark.django_db
def test_resumo_da_cobranca_explica_primeira_cobranca_e_numeros(auth_client, cadastro):
    cadastro["data_inicio"] = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    cadastro["parcelas_ja_pagas"] = "0"
    texto = auth_client.post(reverse("contratos:novo"), cadastro).content.decode()
    assert "Resumo da cobrança" in texto
    assert "primeira cobrança sai em" in texto
    assert "faltam pagar" in texto and "em atraso" in texto and "Débito em atraso hoje" in texto
    assert "R$ 100,00" in texto  # 1.000 ÷ 10


@pytest.mark.django_db
def test_resumo_avisa_que_cobrancas_automaticas_ainda_estao_desligadas(auth_client, cadastro, settings):
    settings.COBRANCAS_EXIGEM_INICIO = True
    texto = auth_client.post(reverse("contratos:novo"), cadastro).content.decode()
    assert "ainda estão desligadas" in texto
