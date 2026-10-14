import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos.models import Pagamento, Vencimento
from apps.pagamentos.proximas import proximas_cobrancas

pytestmark = pytest.mark.django_db


def _parcela(contrato, numero, dias, **extra):
    return Vencimento.objects.create(
        contrato=contrato, numero=numero, valor_previsto=Decimal("300.00"),
        data_vencimento=timezone.localdate() + datetime.timedelta(days=dias), **extra,
    )


def test_lista_so_o_que_ainda_vai_ser_cobrado_agrupado_por_data(auth_client, cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=9)
    _parcela(ct, 1, -3)                                  # atrasada: é do "Cobrar hoje"
    _parcela(ct, 2, 0)                                   # hoje: também do "Cobrar hoje"
    amanha, depois = _parcela(ct, 3, 1), _parcela(ct, 4, 5)
    _parcela(ct, 5, 20)                                  # fora da janela de 14 dias
    paga = _parcela(ct, 6, 2, status=Vencimento.Status.PAGO)
    com_baixa = _parcela(ct, 7, 3)
    Pagamento.objects.create(contrato=ct, vencimento=com_baixa, valor_pago=Decimal("100.00"),
                             data_pagamento=timezone.localdate())

    dados = proximas_cobrancas(14)
    assert [g["data"] for g in dados["grupos"]] == [amanha.data_vencimento, depois.data_vencimento]
    assert dados["quantidade"] == 2 and dados["total"] == Decimal("600.00")
    assert proximas_cobrancas(30)["quantidade"] == 3  # a janela maior inclui a de 20 dias

    html = auth_client.get(reverse("pagamentos:proximas_cobrancas")).content.decode()
    assert "Próximas cobranças" in html and ct.apelido in html and "R$ 600,00" in html
    assert auth_client.get(reverse("pagamentos:proximas_cobrancas") + "?dias=99").status_code == 200


def test_pagina_exige_login():
    from django.test import Client

    assert Client().get(reverse("pagamentos:proximas_cobrancas")).status_code == 302


def test_resumo_da_yslane_traz_promessas_e_os_proximos_3_dias(cliente):
    from apps.pagamentos.lembrete import montar_texto_completo as montar_texto
    from apps.pagamentos.models import ContatoDeCobranca

    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=9)
    _parcela(ct, 1, 2)
    ContatoDeCobranca.objects.create(contrato=ct, resultado="promessa", promessa_para=timezone.localdate())
    hoje = timezone.localdate()
    texto = montar_texto({"hoje": hoje, "linhas": [], "total_previsto": Decimal("0"), "n_atraso": 0, "n_bloqueio": 2})
    assert "não tem ninguém pra cobrar" in texto
    assert "Promessas de pagamento" in texto and cliente.nome in texto
    assert "2 aparelhos para bloquear" in texto and "Próximos 3 dias: 1 cobrança(s), R$ 300,00" in texto


def test_pagina_avisa_contrato_sem_parcelas_geradas_e_tem_atalhos(auth_client, cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=9)
    _parcela(ct, 1, 3)  # só 1 de 9 geradas e a última acaba dentro da janela
    html = auth_client.get(reverse("pagamentos:proximas_cobrancas")).content.decode()
    assert "parcelas ainda não geradas" in html and "editar" in html and "negociar" in html
