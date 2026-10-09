import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.clientes.views import _painel_do_contrato
from apps.contratos.models import Contrato
from apps.pagamentos.agenda import montar_agenda_do_dia
from apps.pagamentos.models import CobrancaCora, Pagamento, Vencimento


@pytest.fixture
def plano(db):
    hoje = timezone.localdate()
    cliente = Cliente.objects.create(nome="Exemplo UX", cpf="11144477735", telefone_whatsapp="+5583999990000")
    contrato = Contrato.objects.create(
        cliente=cliente, apelido="Aparelho", aparelho_modelo="Modelo", valor_total=160,
        valor_parcela=40, num_parcelas=4, estrutura="diaria", data_inicio=hoje-datetime.timedelta(days=3),
    )
    for n in range(1, 5):
        Vencimento.objects.create(contrato=contrato, numero=n, valor_previsto=40,
                                  data_vencimento=hoje+datetime.timedelta(days=n-3))
    return contrato


def test_totais_iguais_em_agenda_cliente_contrato_e_baixa(plano, auth_client):
    resumo = montar_agenda_do_dia()["linhas"][0]["resumo"]
    assert resumo["principal"] == Decimal("120")
    assert resumo["juros"] == Decimal("15")
    assert _painel_do_contrato(plano)["a_cobrar"] == resumo["total"] == Decimal("135")
    for nome, kwargs in [
        ("pagamentos:cobrar_hoje", {}), ("clientes:detalhe", {"pk": plano.cliente_id}),
        ("contratos:detalhe", {"pk": plano.pk}), ("pagamentos:novo", {"contrato_pk": plano.pk}),
    ]:
        html = auth_client.get(reverse(nome, kwargs=kwargs)).content.decode()
        assert "135,00" in html and "3 parcelas: R$ 120,00" in html and "juros: R$ 15,00" in html


@pytest.mark.parametrize("valor,trecho,previstos", [
    ("30,00", "faltam R$ 10,00", [40, 50, 40, 40]),
    ("40,00", "Parcela 1: ficará paga", [40, 40, 40, 40]),
    ("100,00", "Parcela 3: abatimento de R$ 20,00", [40, 0, 20, 40]),
    ("200,00", "R$ 40,00 ficará como crédito", [40, 0, 0, 0]),
])
def test_previa_sem_gravar_e_resultado_corresponde_a_baixa(plano, auth_client, valor, trecho, previstos):
    venc = plano.vencimentos.get(numero=1)
    dados = {"vencimento": venc.pk, "valor_pago": valor, "juros_pago": "5,00",
             "data_pagamento": timezone.localdate().isoformat(), "forma": "dinheiro"}
    resposta = auth_client.post(reverse("pagamentos:previsao", args=[plano.pk]), dados)
    assert resposta.status_code == 200 and trecho in resposta.json()["texto"]
    assert not Pagamento.objects.exists()
    assert list(plano.vencimentos.values_list("valor_previsto", flat=True)) == [40]*4
    Pagamento(contrato=plano, vencimento=venc, valor_pago=Decimal(valor.replace(",", ".")),
              juros_pago=5, forma="dinheiro", data_pagamento=timezone.localdate()).registrar()
    assert list(plano.vencimentos.order_by("numero").values_list("valor_previsto", flat=True)) == previstos


def test_previa_recusa_parcela_de_outro_contrato(plano, auth_client):
    outro = Contrato.objects.create(cliente=plano.cliente, apelido="Outro", valor_total=40,
                                    data_inicio=timezone.localdate(), estrutura="diaria")
    resposta = auth_client.post(reverse("pagamentos:previsao", args=[outro.pk]), {
        "vencimento": plano.vencimentos.first().pk, "valor_pago": "40", "forma": "pix",
        "data_pagamento": timezone.localdate().isoformat(),
    })
    assert "Confira a parcela" in resposta.json()["texto"]
    assert not Pagamento.objects.exists()


def test_previa_sem_parcela_pede_correcao(plano, auth_client):
    resposta = auth_client.post(reverse("pagamentos:previsao", args=[plano.pk]), {
        "valor_pago": "40", "forma": "pix", "data_pagamento": timezone.localdate().isoformat(),
    })
    assert resposta.status_code == 200 and "Confira a parcela" in resposta.json()["texto"]
    assert not Pagamento.objects.exists()


@pytest.mark.parametrize("estrutura,dia,primeira,ultima", [
    ("semanal", {"dia_semana": "5"}, "07/02/2026", "14/02/2026"),  # sábados
    ("quinzenal", {"quinzena": "semana", "dia_semana": "5"}, "14/02/2026", "28/02/2026"),  # a cada 14 dias
    ("quinzenal", {"quinzena": "dias_mes", "dia_mes": "5", "dia_mes_2": "20"}, "20/02/2026", "05/03/2026"),
    ("mensal", {"dia_mes": "31"}, "28/02/2026", "31/03/2026"),
])
@pytest.mark.django_db
def test_previa_contrato_calcula_parcela_e_datas(auth_client, estrutura, dia, primeira, ultima):
    texto = auth_client.post(reverse("contratos:previsao"), {
        "valor_total": "75,00", "num_parcelas": "2",
        "estrutura": estrutura, "data_inicio": "2026-01-31", **dia,
    }).json()["texto"]
    assert "2 parcelas de R$ 37,50" in texto and primeira in texto and ultima in texto
    assert "totais são diferentes" not in texto  # a parcela sai do total ÷ nº de parcelas
    assert not Contrato.objects.exists()


def test_alerta_pix_no_inicio_e_menu_mobile(plano, auth_client):
    CobrancaCora.objects.create(vencimento=plano.vencimentos.first(), valor=120,
                               data_vencimento=timezone.localdate(), duplicada=True)
    html = auth_client.get(reverse("relatorios:inicio")).content.decode()
    assert "Conferir pendências" in html and "1 pendência no Pix" in html


@pytest.mark.django_db
def test_previa_exige_login(client):
    assert client.post(reverse("contratos:previsao"), {}).status_code == 302
