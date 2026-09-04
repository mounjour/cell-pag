import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import CobrancaPix, EventoCora, Pagamento, Vencimento
from apps.pagamentos.pix_cora import obter_ou_criar_pix, reconciliar_abertas, sincronizar_pix


date = datetime.date


@pytest.fixture
def parcela_cora(db):
    cliente = Cliente.objects.create(
        nome="Cliente Cora",
        cpf=CPFGen().generate(),
        telefone_whatsapp="+5583999994444",
    )
    contrato = Contrato.objects.create(
        cliente=cliente,
        apelido="Galaxy S23",
        aparelho_modelo="Galaxy S23",
        valor_total=Decimal("500.00"),
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("100.00"),
        num_parcelas=5,
        data_inicio=date(2026, 8, 4),
        proximo_vencimento=date(2026, 9, 4),
    )
    return Vencimento.objects.create(
        contrato=contrato,
        numero=1,
        data_vencimento=date(2026, 9, 4),
        valor_previsto=Decimal("100.00"),
    )


@pytest.mark.django_db
def test_modo_log_prepara_sem_chamar_cora(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "log"
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda *args, **kwargs: pytest.fail("não deveria chamar a Cora"),
    )
    pix = obter_ou_criar_pix(parcela_cora, hoje=date(2026, 9, 4))
    assert pix.status == CobrancaPix.Status.PENDENTE
    assert pix.cora_id is None


@pytest.mark.django_db
def test_cria_pix_com_idempotencia_e_valor_em_centavos(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    chamada = {}

    def criar(payload, chave):
        chamada.update(payload=payload, chave=chave)
        return {
            "id": "inv_123",
            "status": "OPEN",
            "total_paid": 0,
            "pix": {"emv": "000201PIX-COPIA-E-COLA"},
            "payment_options": {"bank_slip": {"url": "https://cora.example/qr.png"}},
        }

    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", criar)
    pix = obter_ou_criar_pix(parcela_cora, hoje=date(2026, 9, 4))
    assert chamada["payload"]["services"][0]["amount"] == 10000
    assert chamada["chave"] == pix.idempotency_key
    assert pix.status == CobrancaPix.Status.ABERTO
    assert pix.cora_id == "inv_123"
    assert pix.pix_copia_e_cola == "000201PIX-COPIA-E-COLA"


@pytest.mark.django_db
def test_confirmacao_cora_da_baixa_automatica(parcela_cora, monkeypatch):
    pix = CobrancaPix.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_pago",
        status=CobrancaPix.Status.ABERTO,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {
            "id": cora_id,
            "status": "PAID",
            "total_paid": 10000,
            "occurrence_date": "2026-09-04T12:00:00Z",
            "pix": {"emv": "PIX"},
        },
    )
    sincronizar_pix(pix)
    pix.refresh_from_db()
    assert pix.status == CobrancaPix.Status.PAGO
    pagamento = Pagamento.objects.get(vencimento=parcela_cora)
    assert pagamento.valor_pago == Decimal("100.00")
    assert pagamento.usuario_baixa is None
    assert "inv_pago" in pagamento.observacao


@pytest.mark.django_db
def test_reconciliacao_processa_sinal_do_webhook(parcela_cora, monkeypatch):
    pix = CobrancaPix.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_sinal",
        status=CobrancaPix.Status.ABERTO,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    evento = EventoCora.objects.create(
        evento_id="evt",
        tipo="invoice.paid",
        recurso_id="inv_sinal",
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "OPEN", "total_paid": 0, "pix": {"emv": "PIX"}},
    )
    resultado = reconciliar_abertas()
    evento.refresh_from_db()
    assert resultado["consultadas"] == 1
    assert evento.processado is True


@pytest.mark.django_db
def test_webhook_cora_so_registra_fatura_conhecida(client, parcela_cora, monkeypatch):
    CobrancaPix.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_conhecida",
        status=CobrancaPix.Status.ABERTO,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda *args: pytest.fail("webhook público não pode consultar API autenticada"),
    )
    cabecalhos = {
        "webhook-event-type": "invoice.paid",
        "webhook-resource-id": "inv_conhecida",
    }
    primeira = client.post(reverse("pagamentos:cora_webhook"), headers=cabecalhos)
    segunda = client.post(reverse("pagamentos:cora_webhook"), headers=cabecalhos)
    assert primeira.status_code == segunda.status_code == 200
    assert EventoCora.objects.count() == 1


@pytest.mark.django_db
def test_painel_pix_exige_login(client):
    resposta = client.get(reverse("pagamentos:pix_painel"))
    assert resposta.status_code == 302


@pytest.mark.django_db
def test_painel_pix_mostra_pago_e_nao_pago(auth_client, parcela_cora):
    CobrancaPix.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_atrasada",
        status=CobrancaPix.Status.VENCIDO,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    resposta = auth_client.get(reverse("pagamentos:pix_painel"))
    assert resposta.status_code == 200
    assert "Não pago" in resposta.content.decode()
