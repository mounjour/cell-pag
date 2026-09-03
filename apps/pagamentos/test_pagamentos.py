"""Testes da Fase 3 — registro de pagamento, baixa, parcial e trilha.

Regras (PLANO-DO-PROJETO.md, seções 4.4 e 6; decisões desta conversa):

* uma linha de ``Pagamento`` por parcela (``UniqueConstraint(contrato, vencimento)``);
* parcial: parcela vira ``parcial`` e o saldo entra no ``valor_previsto`` da
  próxima parcela em aberto (ou em ``Contrato.saldo_transportado``);
* a baixa não quita o contrato (quitar é manual — ``contratos:quitar``).
"""

import datetime
from decimal import Decimal

import pytest
from auditlog.models import LogEntry
from django.db import IntegrityError, transaction
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import Pagamento, Vencimento

date = datetime.date


@pytest.fixture
def cliente(db):
    c = Cliente(nome="Fulano de Tal", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    c.full_clean()
    c.save()
    return c


def _contrato(cliente, **kwargs):
    dados = dict(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        valor_total=Decimal("400.00"),
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("40.00"),
        num_parcelas=10,
        data_inicio=date(2026, 2, 20),
    )
    dados.update(kwargs)
    return Contrato.objects.create(**dados)


def _contrato_com_parcelas(cliente, **kwargs):
    ct = _contrato(cliente, **kwargs)
    ct.gerar_vencimentos(dias_a_frente=3650, hoje=date(2026, 2, 20))
    return ct


def _baixa(contrato, numero, valor, **kwargs):
    """Cria e registra um Pagamento na parcela ``numero`` do contrato."""
    venc = contrato.vencimentos.get(numero=numero)
    pag = Pagamento(
        contrato=contrato,
        vencimento=venc,
        valor_pago=Decimal(valor),
        forma=Pagamento.Forma.PIX,
        **kwargs,
    )
    pag.registrar()
    return pag


# ── baixa: efeito na parcela e no contrato ──────────────────────────────────

@pytest.mark.django_db
def test_baixa_total_marca_parcela_paga_sem_quitar_contrato(cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "40.00")

    v1 = ct.vencimentos.get(numero=1)
    assert v1.status == Vencimento.Status.PAGO
    assert v1.valor_pago == Decimal("40.00")
    ct.refresh_from_db()
    assert ct.status != Contrato.Status.QUITADO  # baixa nunca quita


@pytest.mark.django_db
def test_baixa_parcial_transporta_saldo_para_a_proxima(cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "30.00")

    v1 = ct.vencimentos.get(numero=1)
    v2 = ct.vencimentos.get(numero=2)
    assert v1.status == Vencimento.Status.PARCIAL
    assert v2.valor_previsto == Decimal("50.00")  # 40 + 10 que faltaram
    ct.refresh_from_db()
    assert ct.saldo_transportado == Decimal("0.00")


@pytest.mark.django_db
def test_parcial_na_ultima_parcela_vai_para_saldo_transportado(cliente):
    ct = _contrato_com_parcelas(cliente, num_parcelas=2)
    _baixa(ct, 1, "40.00")
    _baixa(ct, 2, "30.00")

    ct.refresh_from_db()
    assert ct.saldo_transportado == Decimal("10.00")
    assert ct.vencimentos.get(numero=2).status == Vencimento.Status.PARCIAL


@pytest.mark.django_db
def test_pagamento_a_maior_abate_a_proxima(cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "50.00")

    assert ct.vencimentos.get(numero=1).status == Vencimento.Status.PAGO
    assert ct.vencimentos.get(numero=2).valor_previsto == Decimal("30.00")  # 40 - 10


@pytest.mark.django_db
def test_pagamento_a_maior_cascateia_pelas_proximas(cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "120.00")  # 40 da parcela + 80 de crédito

    assert ct.vencimentos.get(numero=2).valor_previsto == Decimal("0.00")
    assert ct.vencimentos.get(numero=3).valor_previsto == Decimal("0.00")
    assert ct.vencimentos.get(numero=4).valor_previsto == Decimal("40.00")


@pytest.mark.django_db
def test_gerar_vencimentos_drena_saldo_transportado(cliente):
    ct = _contrato(cliente, num_parcelas=5)
    ct.gerar_vencimentos(dias_a_frente=1, hoje=date(2026, 2, 20))  # gera só as 1ªs
    assert ct.vencimentos.count() < 5
    Contrato.objects.filter(pk=ct.pk).update(saldo_transportado=Decimal("15.00"))
    ct.refresh_from_db()

    novos = ct.gerar_vencimentos(dias_a_frente=3650, hoje=date(2026, 2, 20))
    assert novos, "esperava novas parcelas"
    assert novos[0].valor_previsto == Decimal("55.00")  # 40 + 15
    ct.refresh_from_db()
    assert ct.saldo_transportado == Decimal("0.00")


# ── constraints ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_uma_baixa_por_parcela(cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "20.00")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Pagamento.objects.create(
                contrato=ct,
                vencimento=ct.vencimentos.get(numero=1),
                valor_pago=Decimal("20.00"),
            )


@pytest.mark.django_db
def test_valor_pago_precisa_ser_positivo(cliente):
    ct = _contrato_com_parcelas(cliente)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Pagamento.objects.create(
                contrato=ct,
                vencimento=ct.vencimentos.get(numero=1),
                valor_pago=Decimal("0.00"),
            )


# ── telas ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_registrar_exige_login(client, cliente):
    ct = _contrato_com_parcelas(cliente)
    resp = client.get(reverse("pagamentos:novo", args=[ct.pk]))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_get_preseleciona_parcela_aberta_e_valor(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    resp = auth_client.get(reverse("pagamentos:novo", args=[ct.pk]))
    assert resp.status_code == 200
    v1 = ct.vencimentos.get(numero=1)
    assert resp.context["form"].initial["vencimento"] == v1.pk
    assert resp.context["form"].initial["valor_pago"] == "40,00"


@pytest.mark.django_db
def test_post_cria_baixa_e_redireciona(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    v1 = ct.vencimentos.get(numero=1)
    resp = auth_client.post(
        reverse("pagamentos:novo", args=[ct.pk]),
        {
            "vencimento": v1.pk,
            "data_pagamento": "2026-03-01",
            "valor_pago": "40,00",
            "forma": "pix",
            "observacao": "",
        },
    )
    assert resp.status_code == 302
    assert resp["Location"] == reverse("contratos:detalhe", args=[ct.pk])
    assert Pagamento.objects.count() == 1
    pag = Pagamento.objects.get()
    assert pag.usuario_baixa is not None
    v1.refresh_from_db()
    assert v1.status == Vencimento.Status.PAGO


@pytest.mark.django_db
def test_post_em_parcela_ja_com_baixa_da_erro_de_form(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "30.00")  # parcial — parcela segue no queryset
    v1 = ct.vencimentos.get(numero=1)
    resp = auth_client.post(
        reverse("pagamentos:novo", args=[ct.pk]),
        {
            "vencimento": v1.pk,
            "data_pagamento": "2026-03-02",
            "valor_pago": "10,00",
            "forma": "pix",
        },
    )
    assert resp.status_code == 200
    assert resp.context["form"].errors
    assert Pagamento.objects.count() == 1


@pytest.mark.django_db
def test_data_futura_e_recusada(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    v1 = ct.vencimentos.get(numero=1)
    futuro = (date.today() + datetime.timedelta(days=3)).isoformat()
    resp = auth_client.post(
        reverse("pagamentos:novo", args=[ct.pk]),
        {"vencimento": v1.pk, "data_pagamento": futuro, "valor_pago": "40,00", "forma": "pix"},
    )
    assert resp.status_code == 200
    assert "data_pagamento" in resp.context["form"].errors
    assert not Pagamento.objects.exists()


@pytest.mark.django_db
def test_cliente_detalhe_lista_pagamentos(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "40.00", data_pagamento=date(2026, 3, 1))
    resp = auth_client.get(reverse("clientes:detalhe", args=[cliente.pk]))
    assert resp.status_code == 200
    assert resp.context["pagamentos_total"] == 1
    corpo = resp.content.decode()
    assert "Pagamentos" in corpo
    assert "01/03/2026" in corpo


@pytest.mark.django_db
def test_historico_filtra_por_cliente(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "40.00")
    resp = auth_client.get(reverse("pagamentos:historico"), {"cliente": cliente.pk})
    assert resp.status_code == 200
    assert list(resp.context["pagamentos"]) == list(Pagamento.objects.all())
    assert resp.context["filtrado"] is True


# ── quitação manual ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_quitar_marca_quitado_e_calcula_data(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente, num_parcelas=3)
    resp = auth_client.post(reverse("contratos:quitar", args=[ct.pk]))
    assert resp.status_code == 302
    ct.refresh_from_db()
    assert ct.status == Contrato.Status.QUITADO
    assert ct.data_prevista_quitacao is not None


@pytest.mark.django_db
def test_quitar_por_get_nao_altera(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    resp = auth_client.get(reverse("contratos:quitar", args=[ct.pk]))
    assert resp.status_code == 405
    ct.refresh_from_db()
    assert ct.status != Contrato.Status.QUITADO


@pytest.mark.django_db
def test_detalhe_oferece_quitar_quando_tudo_pago(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente, num_parcelas=2)
    _baixa(ct, 1, "40.00")
    _baixa(ct, 2, "40.00")
    resp = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]))
    assert resp.context["pode_quitar"] is True
    assert "Marcar como quitado" in resp.content.decode()


# ── estorno ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_estorno_remove_e_reverte_a_parcela(auth_client, cliente):
    ct = _contrato_com_parcelas(cliente)
    pag = _baixa(ct, 1, "40.00")
    resp = auth_client.post(reverse("pagamentos:estornar", args=[ct.pk, pag.pk]))
    assert resp.status_code == 302
    assert not Pagamento.objects.filter(pk=pag.pk).exists()
    v1 = ct.vencimentos.get(numero=1)
    assert v1.status == Vencimento.Status.ABERTO
    assert v1.valor_pago == Decimal("0.00")


# ── trilha de auditoria ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_baixa_gera_registro_no_auditlog(cliente):
    ct = _contrato_com_parcelas(cliente)
    _baixa(ct, 1, "40.00")
    assert LogEntry.objects.filter(content_type__model="pagamento").exists()
