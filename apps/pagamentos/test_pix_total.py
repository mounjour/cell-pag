"""Pix pelo total das parcelas vencidas do contrato (uma fatura, várias parcelas)."""

import datetime
from decimal import Decimal

import pytest
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import CobrancaCora, Pagamento, Vencimento
from apps.pagamentos.pix_cora import obter_ou_criar_cobranca, sincronizar_cobranca

date = datetime.date
HOJE = date(2026, 9, 28)


@pytest.mark.django_db
@pytest.mark.parametrize("pago_por_fora", ["5.00", "10.00"])
def test_pix_antigo_apos_baixa_manual_exige_revisao(settings, monkeypatch, pago_por_fora):
    settings.CORA_PROVIDER = "cora"
    monkeypatch.setattr("apps.pagamentos.pix_cora.timezone.localdate", lambda: HOJE)
    contrato = _contrato_com_parcelas(3)
    futura = Vencimento.objects.create(
        contrato=contrato, numero=4, data_vencimento=date(2026, 9, 29),
        valor_previsto=Decimal("10.00"),
    )
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    cobranca = obter_ou_criar_cobranca(contrato.vencimentos.get(numero=1), hoje=HOJE)
    Pagamento(
        contrato=contrato, vencimento=contrato.vencimentos.get(numero=2),
        data_pagamento=HOJE, valor_pago=Decimal(pago_por_fora), forma=Pagamento.Forma.PIX,
        observacao="Baixa manual",
    ).registrar()
    antes = list(contrato.vencimentos.values_list("pk", "valor_previsto", "valor_pago", "status"))
    pago_no_pix = int(cobranca.valor * 100)  # o QR antigo: 3 parcelas + juros
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura", lambda cid: _fatura(cid, "PAID", pago_no_pix),
    )
    monkeypatch.setattr(
        "apps.pagamentos.pix_cora.ao_confirmar_pix", lambda *a: pytest.fail("Não confirmar baixa retida"),
    )
    sincronizar_cobranca(cobranca)
    sincronizar_cobranca(cobranca)
    cobranca.refresh_from_db()
    assert cobranca.duplicada and cobranca.status == CobrancaCora.Status.PAGO
    assert Pagamento.objects.count() == 1
    assert list(contrato.vencimentos.values_list("pk", "valor_previsto", "valor_pago", "status")) == antes
    futura.refresh_from_db()
    assert futura.valor_previsto == Decimal("10.00")


def _contrato_com_parcelas(dias_vencidos):
    """Parcelas de R$ 10 vencendo 26, 27 e 28/09 (só as ``dias_vencidos`` primeiras existem)."""
    cliente = Cliente.objects.create(
        nome="Cliente Total", cpf=CPFGen().generate(), telefone_whatsapp="+5583999995555"
    )
    contrato = Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11",
        valor_total=Decimal("30.00"),
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("10.00"),
        num_parcelas=3,
        data_inicio=date(2026, 9, 25),
    )
    for n in range(1, dias_vencidos + 1):
        Vencimento.objects.create(
            contrato=contrato,
            numero=n,
            data_vencimento=date(2026, 9, 25 + n),
            valor_previsto=Decimal("10.00"),
        )
    return contrato


def _fatura(id_, status="OPEN", pago=0):
    return {"id": id_, "status": status, "total_paid": pago, "pix": {"emv": f"PIX-{id_}"}}


@pytest.mark.django_db
def test_pix_cobra_o_total_das_parcelas_vencidas(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(3)
    enviado = {}

    def criar(payload, chave):
        enviado.update(payload)
        return _fatura("inv_1")

    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", criar)
    cobranca = obter_ou_criar_cobranca(contrato.vencimentos.get(numero=1), hoje=HOJE)

    assert enviado["services"][0]["amount"] == 4500  # 3 x R$ 10 + R$ 15 de juros (2 + 1 dias a R$ 5)
    assert enviado["services"][0]["name"] == "Parcelas 1, 2, 3 + juros"
    assert cobranca.valor == Decimal("45.00") and cobranca.juros == Decimal("15.00")
    assert cobranca.vencimento.numero == 1  # preso à mais antiga


@pytest.mark.django_db
def test_uma_parcela_so_continua_cobrando_so_ela(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(1)
    enviado = {}
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda payload, chave: enviado.update(payload) or _fatura("inv_1"),
    )
    obter_ou_criar_cobranca(contrato.vencimentos.get(numero=1), hoje=HOJE)
    assert enviado["services"][0]["amount"] == 2000  # R$ 10 + 2 dias de juros (R$ 10)
    assert enviado["services"][0]["name"] == "Parcela 1 + juros"


@pytest.mark.django_db
def test_total_que_mudou_troca_o_pix_antigo_por_um_novo(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(2)
    v1 = contrato.vencimentos.get(numero=1)
    criadas = []

    def criar(payload, chave):
        criadas.append(payload["services"][0]["amount"])
        return _fatura(f"inv_{len(criadas)}")

    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", criar)
    antigo = obter_ou_criar_cobranca(v1, hoje=date(2026, 9, 27))  # 2 parcelas (R$ 20) + R$ 5 de juros
    assert antigo.valor == Decimal("25.00") and antigo.cora_id == "inv_1"

    # No dia seguinte entra a parcela 3 e o total passa a R$ 45 (R$ 30 + R$ 15 de juros).
    Vencimento.objects.create(
        contrato=contrato, numero=3, data_vencimento=HOJE, valor_previsto=Decimal("10.00")
    )
    estados = iter(["OPEN", "CANCELLED"])
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": next(estados), "total_paid": 0},
    )
    canceladas = []
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura", lambda cora_id: canceladas.append(cora_id) or {}
    )

    novo = obter_ou_criar_cobranca(v1, hoje=HOJE)

    assert canceladas == ["inv_1"]
    assert criadas == [2500, 4500]
    assert novo.pk == antigo.pk  # mesmo registro, nova fatura
    assert novo.cora_id == "inv_2" and novo.valor == Decimal("45.00") and novo.juros == Decimal("15.00")
    assert novo.pix_copia_e_cola == "PIX-inv_2"


@pytest.mark.django_db
def test_mesmo_total_nao_recria_a_fatura(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(3)
    v1 = contrato.vencimentos.get(numero=1)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    obter_ou_criar_cobranca(v1, hoje=HOJE)
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda *a, **k: pytest.fail("não deveria criar outra fatura"),
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura",
        lambda *a, **k: pytest.fail("não deveria cancelar"),
    )
    assert obter_ou_criar_cobranca(v1, hoje=HOJE).cora_id == "inv_1"


@pytest.mark.django_db
def test_nao_troca_o_pix_se_o_cliente_acabou_de_pagar(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(2)
    v1 = contrato.vencimentos.get(numero=1)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    obter_ou_criar_cobranca(v1, hoje=date(2026, 9, 27))

    Vencimento.objects.create(
        contrato=contrato, numero=3, data_vencimento=HOJE, valor_previsto=Decimal("10.00")
    )
    # A consulta antes de cancelar descobre que o Pix de R$ 20 já foi pago.
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: _fatura(cora_id, "PAID", pago=2500),
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura",
        lambda *a, **k: pytest.fail("não pode cancelar Pix pago"),
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda *a, **k: pytest.fail("não pode criar outro Pix"),
    )

    cobranca = obter_ou_criar_cobranca(v1, hoje=HOJE)

    assert cobranca.status == CobrancaCora.Status.PAGO
    assert cobranca.cora_id == "inv_1"


@pytest.mark.django_db
def test_falha_ao_cancelar_mantem_o_pix_antigo(settings, monkeypatch):
    from apps.pagamentos import cora_api

    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(2)
    v1 = contrato.vencimentos.get(numero=1)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    obter_ou_criar_cobranca(v1, hoje=date(2026, 9, 27))
    Vencimento.objects.create(
        contrato=contrato, numero=3, data_vencimento=HOJE, valor_previsto=Decimal("10.00")
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "OPEN", "total_paid": 0},
    )

    def falha(cora_id):
        raise cora_api.CoraErro("fora do ar")

    monkeypatch.setattr("apps.pagamentos.cora_api.cancelar_fatura", falha)
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda *a, **k: pytest.fail("com o antigo vivo, não pode criar outro"),
    )

    cobranca = obter_ou_criar_cobranca(v1, hoje=HOJE)

    assert cobranca.cora_id == "inv_1"
    assert "fora do ar" in cobranca.erro


@pytest.mark.django_db
def test_pagar_o_pix_total_quita_todas_as_parcelas(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(3)
    v1 = contrato.vencimentos.get(numero=1)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    cobranca = obter_ou_criar_cobranca(v1, hoje=HOJE)

    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: _fatura(cora_id, "PAID", pago=4500),
    )
    monkeypatch.setattr("apps.pagamentos.pix_cora.ao_confirmar_pix", lambda *a, **k: None)
    sincronizar_cobranca(cobranca)

    assert Pagamento.objects.count() == 1
    pagamento = Pagamento.objects.get()
    # R$ 45 pagos no Pix = R$ 30 das parcelas + R$ 15 de juros (campo próprio)
    assert pagamento.valor_pago == Decimal("30.00") and pagamento.juros_pago == Decimal("15.00")
    status = list(contrato.vencimentos.order_by("numero").values_list("status", flat=True))
    assert status == ["pago", "pago", "pago"]  # as duas seguintes quitadas pelo crédito
    assert contrato.parcela_em_aberto() is None  # nada mais a cobrar amanhã


@pytest.mark.django_db
def test_painel_pix_mostra_as_parcelas_que_o_pix_cobre(auth_client, settings, monkeypatch):
    from django.urls import reverse
    from django.utils import timezone

    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(3)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    obter_ou_criar_cobranca(contrato.vencimentos.get(numero=1), hoje=HOJE)
    monkeypatch.setattr(timezone, "localdate", lambda: HOJE)

    html = auth_client.get(reverse("pagamentos:pix_painel")).content.decode()
    assert '<td data-label="Parcela" class="num">1, 2, 3</td>' in html


# ── Cobrança sempre com juros (parcela + juros; não existe pagar só a parcela) ──

@pytest.mark.django_db
def test_pix_de_uma_parcela_atrasada_cobra_parcela_mais_juros(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(1)  # parcela 1 venceu 26/09; hoje 28/09 = 2 dias de atraso
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    cobranca = obter_ou_criar_cobranca(contrato.vencimentos.get(numero=1), hoje=HOJE)
    assert (cobranca.valor, cobranca.juros) == (Decimal("20.00"), Decimal("10.00"))


@pytest.mark.django_db
def test_parcela_que_vence_hoje_nao_tem_juros(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(3)
    contrato.vencimentos.filter(numero__lt=3).delete()
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    cobranca = obter_ou_criar_cobranca(contrato.vencimentos.get(numero=3), hoje=HOJE)
    assert (cobranca.valor, cobranca.juros) == (Decimal("10.00"), Decimal("0.00"))


@pytest.mark.django_db
def test_baixa_do_pix_registra_o_juros_a_parte_e_so_o_principal_abate_a_parcela(settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(1)
    v1 = contrato.vencimentos.get(numero=1)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    cobranca = obter_ou_criar_cobranca(v1, hoje=HOJE)  # R$ 10 + R$ 10 de juros
    monkeypatch.setattr("apps.pagamentos.cora_api.consultar_fatura", lambda cid: _fatura(cid, "PAID", pago=2000))
    monkeypatch.setattr("apps.pagamentos.pix_cora.ao_confirmar_pix", lambda *a, **k: None)
    sincronizar_cobranca(cobranca)

    pagamento = Pagamento.objects.get()
    assert (pagamento.valor_pago, pagamento.juros_pago) == (Decimal("10.00"), Decimal("10.00"))
    v1.refresh_from_db()
    assert v1.status == "pago" and v1.valor_pago == Decimal("10.00")  # o juros não vira "troco" da parcela
    assert not CobrancaCora.objects.get(pk=cobranca.pk).duplicada


@pytest.mark.django_db
def test_pagar_o_qr_de_ontem_logo_cedo_nao_cai_em_revisao_manual(settings, monkeypatch):
    """O juros cresce R$ 5 por dia: quem paga o QR de ontem antes da rotina refazê-lo é pagamento válido."""
    settings.CORA_PROVIDER = "cora"
    contrato = _contrato_com_parcelas(3)
    v1 = contrato.vencimentos.get(numero=1)
    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", lambda p, k: _fatura("inv_1"))
    cobranca = obter_ou_criar_cobranca(v1, hoje=HOJE)  # QR de R$ 45
    amanha = HOJE + datetime.timedelta(days=1)
    monkeypatch.setattr("apps.pagamentos.pix_cora.timezone.localdate", lambda: amanha)
    monkeypatch.setattr("apps.pagamentos.cora_api.consultar_fatura", lambda cid: _fatura(cid, "PAID", pago=4500))
    monkeypatch.setattr("apps.pagamentos.pix_cora.ao_confirmar_pix", lambda *a, **k: None)
    sincronizar_cobranca(cobranca)

    assert Pagamento.objects.count() == 1
    assert not CobrancaCora.objects.get(pk=cobranca.pk).duplicada


@pytest.mark.django_db
def test_confirmacao_ao_cliente_detalha_parcela_e_juros(settings, monkeypatch):
    from apps.pagamentos.comprovantes import enviar_confirmacao

    contrato = _contrato_com_parcelas(1)
    cobranca = CobrancaCora.objects.create(
        vencimento=contrato.vencimentos.get(numero=1), valor=Decimal("20.00"), juros=Decimal("10.00"),
        total_pago=Decimal("20.00"), data_vencimento=HOJE, cora_id="inv_x", status=CobrancaCora.Status.PAGO,
    )
    enviados = []
    monkeypatch.setattr("apps.pagamentos.comprovantes.enviar_mensagem", lambda **k: enviados.append(k["texto"]) or {"id": "1"})
    assert enviar_confirmacao(cobranca.pk)
    assert "R$ 20,00, sendo R$ 10,00 de parcela e R$ 10,00 de juros" in enviados[0]
