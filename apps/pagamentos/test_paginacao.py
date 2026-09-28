"""Limite de itens por página nas telas Pix e Cobrar hoje."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import CobrancaCora, Vencimento
from apps.pagamentos.views import POR_PAGINA_COBRAR_HOJE, POR_PAGINA_PIX

date = datetime.date


def _contrato(n, **kwargs):
    cliente = Cliente.objects.create(
        nome=f"Cliente {n:03d}", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000"
    )
    dados = dict(
        cliente=cliente,
        apelido=f"Aparelho {n}",
        aparelho_modelo="Modelo",
        valor_total=Decimal("100.00"),
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("10.00"),
        num_parcelas=10,
        data_inicio=date(2020, 1, 1),
    )
    dados.update(kwargs)
    return Contrato.objects.create(**dados)


@pytest.mark.django_db
def test_pix_mostra_no_maximo_uma_pagina_mas_conta_tudo(auth_client):
    total = POR_PAGINA_PIX + 5
    for n in range(total):
        ct = _contrato(n)
        venc = Vencimento.objects.create(
            contrato=ct, numero=1, data_vencimento=date(2020, 1, 2), valor_previsto=Decimal("10.00")
        )
        CobrancaCora.objects.create(
            vencimento=venc,
            status=CobrancaCora.Status.ABERTO,
            valor=Decimal("10.00"),
            data_vencimento=venc.data_vencimento,
        )

    pagina1 = auth_client.get(reverse("pagamentos:pix_painel"))
    assert len(pagina1.context["cobrancas_cora"]) == POR_PAGINA_PIX
    assert pagina1.context["total"] == total  # o resumo continua sendo do total
    assert "Página 1 de 2" in pagina1.content.decode()

    pagina2 = auth_client.get(reverse("pagamentos:pix_painel"), {"page": 2})
    assert len(pagina2.context["cobrancas_cora"]) == 5


@pytest.mark.django_db
def test_cobrar_hoje_mostra_uma_pagina_e_total_completo(auth_client):
    total = POR_PAGINA_COBRAR_HOJE + 3
    for n in range(total):
        ct = _contrato(n)
        ct.gerar_vencimentos(dias_a_frente=0, hoje=date(2020, 1, 2))

    resposta = auth_client.get(reverse("pagamentos:cobrar_hoje"))
    assert len(resposta.context["linhas"]) == POR_PAGINA_COBRAR_HOJE
    assert resposta.context["total_linhas"] == total
    assert "Página 1 de 2" in resposta.content.decode()


@pytest.mark.django_db
def test_pagina_invalida_nao_da_erro(auth_client):
    resposta = auth_client.get(reverse("pagamentos:pix_painel"), {"page": "999"})
    assert resposta.status_code == 200
    resposta = auth_client.get(reverse("pagamentos:pix_painel"), {"page": "abc"})
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_link_de_pagina_mantem_o_filtro(auth_client):
    for n in range(25):
        _contrato(n)
    resposta = auth_client.get(reverse("clientes:lista"), {"q": "Cliente"})
    html = resposta.content.decode()
    assert "q=Cliente&amp;page=2" in html or "q=Cliente&page=2" in html
