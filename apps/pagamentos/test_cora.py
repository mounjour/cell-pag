import datetime
import io
import urllib.error
from decimal import Decimal

import pytest
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos import cora_api
from apps.pagamentos.models import CobrancaCora, EventoCora, Pagamento, Vencimento
from apps.pagamentos.pix_cora import (
    CancelamentoRecusado,
    cancelar_cobranca,
    obter_ou_criar_cobranca,
    reconciliar_abertas,
    sincronizar_cobranca,
)


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
    cobranca = obter_ou_criar_cobranca(parcela_cora, hoje=date(2026, 9, 4))
    assert cobranca.status == CobrancaCora.Status.PENDENTE
    assert cobranca.cora_id is None


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
        }

    monkeypatch.setattr("apps.pagamentos.cora_api.criar_fatura", criar)
    cobranca = obter_ou_criar_cobranca(parcela_cora, hoje=date(2026, 9, 4))
    assert chamada["payload"]["services"][0]["amount"] == 10000
    assert chamada["payload"]["payment_forms"] == ["PIX"]
    assert chamada["chave"] == cobranca.idempotency_key
    assert cobranca.status == CobrancaCora.Status.ABERTO
    assert cobranca.cora_id == "inv_123"
    assert cobranca.pix_copia_e_cola == "000201PIX-COPIA-E-COLA"


def _pix_aberto(parcela):
    return CobrancaCora.objects.create(
        vencimento=parcela,
        cora_id="inv_cancelar",
        status=CobrancaCora.Status.ABERTO,
        valor=Decimal("100.00"),
        data_vencimento=parcela.data_vencimento,
        pix_copia_e_cola="00020126PIX-VIVO",
        qr_code_url="https://cora.example/qr/vivo.png",
    )


@pytest.mark.django_db
def test_cancelar_pix_em_aberto_cancela_na_cora_e_limpa_o_codigo(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    cobranca = _pix_aberto(parcela_cora)
    estados = iter(["OPEN", "CANCELLED"])  # consulta antes de cancelar, e a confirmação depois
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": next(estados), "total_paid": 0},
    )
    canceladas = []
    monkeypatch.setattr("apps.pagamentos.cora_api.cancelar_fatura", lambda cora_id: canceladas.append(cora_id) or {})

    cancelar_cobranca(cobranca)

    cobranca.refresh_from_db()
    assert canceladas == ["inv_cancelar"]
    assert cobranca.status == CobrancaCora.Status.CANCELADO
    # o código cancelado não pode ser reenviado ao cliente
    assert cobranca.pix_copia_e_cola == ""
    assert cobranca.qr_code_url == ""


@pytest.mark.django_db
def test_cancelar_pix_ja_pago_e_recusado_sem_chamar_a_cora(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    cobranca = _pix_aberto(parcela_cora)
    cobranca.status = CobrancaCora.Status.PAGO
    cobranca.save()
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura",
        lambda cora_id: pytest.fail("não pode cancelar fatura paga"),
    )
    with pytest.raises(CancelamentoRecusado):
        cancelar_cobranca(cobranca)


@pytest.mark.django_db
def test_cancelar_pix_que_a_cora_diz_estar_pago_da_baixa_e_recusa(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    cobranca = _pix_aberto(parcela_cora)  # aqui ainda "aberto": o pagamento acabou de ocorrer
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "PAID", "total_paid": 10000, "pix": {"emv": "PIX"}},
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura",
        lambda cora_id: pytest.fail("não pode cancelar fatura paga"),
    )
    with pytest.raises(CancelamentoRecusado):
        cancelar_cobranca(cobranca)
    assert Pagamento.objects.filter(vencimento=parcela_cora).exists()


@pytest.mark.django_db
def test_cancelar_pix_com_falha_da_cora_deixa_tudo_como_estava(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    cobranca = _pix_aberto(parcela_cora)
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "OPEN", "total_paid": 0, "pix": {"emv": "00020126PIX-VIVO"}},
    )

    def _falha(cora_id):
        raise cora_api.CoraErro("fora do ar")

    monkeypatch.setattr("apps.pagamentos.cora_api.cancelar_fatura", _falha)
    with pytest.raises(cora_api.CoraErro):
        cancelar_cobranca(cobranca)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.ABERTO
    assert cobranca.pix_copia_e_cola == "00020126PIX-VIVO"


@pytest.mark.django_db
def test_cancelar_pix_sem_fatura_na_cora_cancela_so_localmente(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "log"
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, valor=Decimal("100.00"), data_vencimento=parcela_cora.data_vencimento
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura",
        lambda cora_id: pytest.fail("sem fatura na Cora, não há o que cancelar lá"),
    )
    cancelar_cobranca(cobranca)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.CANCELADO
    assert cancelar_cobranca(cobranca).status == CobrancaCora.Status.CANCELADO  # idempotente


@pytest.mark.django_db
def test_botao_cancelar_pix_exige_login_e_post(auth_client, parcela_cora, settings):
    from django.test import Client

    settings.CORA_PROVIDER = "log"
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, valor=Decimal("100.00"), data_vencimento=parcela_cora.data_vencimento
    )
    url = reverse("pagamentos:pix_cancelar", args=[cobranca.pk])
    # `client` e `auth_client` são o mesmo objeto: um cliente novo é o anônimo de verdade.
    assert Client().post(url).status_code == 302  # anônimo vai pro login
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.PENDENTE
    assert auth_client.get(url).status_code == 405


@pytest.mark.django_db
def test_botao_cancelar_pix_cancela_e_volta_para_a_tela_de_origem(auth_client, parcela_cora, settings):
    settings.CORA_PROVIDER = "log"
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, valor=Decimal("100.00"), data_vencimento=parcela_cora.data_vencimento
    )
    resposta = auth_client.post(
        reverse("pagamentos:pix_cancelar", args=[cobranca.pk]),
        {"next": reverse("pagamentos:cobrar_hoje")},
        follow=True,
    )
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.CANCELADO
    assert resposta.redirect_chain[-1][0] == reverse("pagamentos:cobrar_hoje")
    assert "cancelado" in resposta.content.decode().lower()


@pytest.mark.django_db
def test_botao_cancelar_pix_ignora_next_de_outro_site(auth_client, parcela_cora, settings):
    settings.CORA_PROVIDER = "log"
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, valor=Decimal("100.00"), data_vencimento=parcela_cora.data_vencimento
    )
    resposta = auth_client.post(
        reverse("pagamentos:pix_cancelar", args=[cobranca.pk]), {"next": "https://malicioso.example/"}
    )
    assert resposta.status_code == 302
    assert resposta["Location"] == reverse("pagamentos:pix_painel")


@pytest.mark.django_db
def test_botao_cancelar_pix_pago_mostra_erro_e_nao_cancela(auth_client, parcela_cora, settings):
    settings.CORA_PROVIDER = "log"
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
        status=CobrancaCora.Status.PAGO,
    )
    resposta = auth_client.post(reverse("pagamentos:pix_cancelar", args=[cobranca.pk]), follow=True)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.PAGO
    assert "já foi pago" in resposta.content.decode()


@pytest.mark.django_db
def test_botao_cancelar_pix_com_cora_fora_do_ar_avisa_e_nao_altera(auth_client, parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    cobranca = _pix_aberto(parcela_cora)
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "OPEN", "total_paid": 0, "pix": {"emv": "00020126PIX-VIVO"}},
    )

    def _falha(cora_id):
        raise cora_api.CoraErro("fora do ar")

    monkeypatch.setattr("apps.pagamentos.cora_api.cancelar_fatura", _falha)
    resposta = auth_client.post(reverse("pagamentos:pix_cancelar", args=[cobranca.pk]), follow=True)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.ABERTO
    assert "Nada foi alterado" in resposta.content.decode()


@pytest.mark.django_db
def test_pix_cancelado_nao_e_recriado_pela_cora(parcela_cora, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    CobrancaCora.objects.create(
        vencimento=parcela_cora,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
        status=CobrancaCora.Status.CANCELADO,
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda *args, **kwargs: pytest.fail("não pode recriar a fatura de um Pix cancelado"),
    )
    cobranca = obter_ou_criar_cobranca(parcela_cora, hoje=date(2026, 9, 4))
    assert cobranca.status == CobrancaCora.Status.CANCELADO


@pytest.mark.django_db
def test_botoes_de_cancelar_so_aparecem_enquanto_o_pix_esta_em_aberto(auth_client, parcela_cora):
    cobranca = _pix_aberto(parcela_cora)
    url_cancelar = reverse("pagamentos:pix_cancelar", args=[cobranca.pk])
    assert url_cancelar in auth_client.get(reverse("pagamentos:pix_painel")).content.decode()
    cobranca.status = CobrancaCora.Status.PAGO
    cobranca.save()
    assert url_cancelar not in auth_client.get(reverse("pagamentos:pix_painel")).content.decode()


# ── Suspender / retomar a cobrança automática de uma parcela ────────────────

@pytest.mark.django_db
def test_suspender_antes_de_existir_pix_registra_pix_cancelado(parcela_cora, settings, monkeypatch):
    from apps.pagamentos.pix_cora import suspender_cobranca

    settings.CORA_PROVIDER = "cora"
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda *args, **kwargs: pytest.fail("suspensa: não pode criar fatura na Cora"),
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.cancelar_fatura",
        lambda cora_id: pytest.fail("não havia fatura para cancelar"),
    )
    cobranca = suspender_cobranca(parcela_cora)
    assert cobranca.status == CobrancaCora.Status.CANCELADO
    assert cobranca.cora_id is None
    # a rotina diária passa por aqui e não recria a fatura
    assert obter_ou_criar_cobranca(parcela_cora, hoje=date(2026, 9, 4)).status == CobrancaCora.Status.CANCELADO


@pytest.mark.django_db
def test_suspender_com_pix_aberto_cancela_na_cora(parcela_cora, settings, monkeypatch):
    from apps.pagamentos.pix_cora import suspender_cobranca

    settings.CORA_PROVIDER = "cora"
    _pix_aberto(parcela_cora)
    estados = iter(["OPEN", "CANCELLED"])
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": next(estados), "total_paid": 0},
    )
    canceladas = []
    monkeypatch.setattr("apps.pagamentos.cora_api.cancelar_fatura", lambda cora_id: canceladas.append(cora_id) or {})
    cobranca = suspender_cobranca(parcela_cora)
    assert canceladas == ["inv_cancelar"]
    assert cobranca.status == CobrancaCora.Status.CANCELADO


@pytest.mark.django_db
def test_suspender_parcela_paga_e_recusado(parcela_cora):
    from apps.pagamentos.pix_cora import suspender_cobranca

    parcela_cora.status = Vencimento.Status.PAGO
    parcela_cora.save()
    with pytest.raises(CancelamentoRecusado):
        suspender_cobranca(parcela_cora)
    assert not CobrancaCora.objects.exists()


@pytest.mark.django_db
def test_retomar_zera_o_registro_e_a_proxima_rotina_gera_fatura_nova(parcela_cora, settings, monkeypatch):
    from apps.pagamentos.pix_cora import retomar_cobranca

    settings.CORA_PROVIDER = "cora"
    cobranca = _pix_aberto(parcela_cora)
    cobranca.status = CobrancaCora.Status.CANCELADO
    cobranca.pix_copia_e_cola = ""
    cobranca.qr_code_url = ""
    cobranca.save()
    chave_antiga = cobranca.idempotency_key

    retomar_cobranca(cobranca)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.PENDENTE
    assert cobranca.cora_id is None
    assert cobranca.idempotency_key != chave_antiga

    monkeypatch.setattr(
        "apps.pagamentos.cora_api.criar_fatura",
        lambda payload, chave: {"id": "inv_nova", "status": "OPEN", "total_paid": 0, "pix": {"emv": "000201NOVO"}},
    )
    nova = obter_ou_criar_cobranca(parcela_cora, hoje=date(2026, 9, 4))
    assert nova.cora_id == "inv_nova"
    assert nova.status == CobrancaCora.Status.ABERTO


@pytest.mark.django_db
def test_views_suspender_e_retomar(auth_client, parcela_cora, settings):
    from django.test import Client

    settings.CORA_PROVIDER = "log"
    url_suspender = reverse("pagamentos:cobranca_suspender", args=[parcela_cora.pk])
    assert Client().post(url_suspender).status_code == 302  # anônimo → login
    assert not CobrancaCora.objects.exists()
    assert auth_client.get(url_suspender).status_code == 405

    destino = reverse("clientes:detalhe", args=[parcela_cora.contrato.cliente_id])
    resposta = auth_client.post(url_suspender, {"next": destino}, follow=True)
    cobranca = CobrancaCora.objects.get(vencimento=parcela_cora)
    assert cobranca.status == CobrancaCora.Status.CANCELADO
    assert resposta.redirect_chain[-1][0] == destino
    assert "suspensa" in resposta.content.decode()

    resposta = auth_client.post(reverse("pagamentos:cobranca_retomar", args=[cobranca.pk]), {"next": destino}, follow=True)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.PENDENTE
    assert "retomada" in resposta.content.decode()


@pytest.mark.django_db
def test_tela_do_cliente_mostra_suspender_e_depois_retomar(auth_client, parcela_cora, settings):
    settings.CORA_PROVIDER = "log"
    url = reverse("clientes:detalhe", args=[parcela_cora.contrato.cliente_id])
    corpo = auth_client.get(url).content.decode()
    assert reverse("pagamentos:cobranca_suspender", args=[parcela_cora.pk]) in corpo
    assert "Registrar pagamento" in corpo

    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora, valor=Decimal("100.00"), data_vencimento=parcela_cora.data_vencimento,
        status=CobrancaCora.Status.CANCELADO,
    )
    corpo = auth_client.get(url).content.decode()
    assert reverse("pagamentos:cobranca_retomar", args=[cobranca.pk]) in corpo
    assert reverse("pagamentos:cobranca_suspender", args=[parcela_cora.pk]) not in corpo
    assert "cobrança automática suspensa" in corpo  # aparece nos avisos


@pytest.mark.django_db
def test_cobrar_hoje_so_mostra_avisos_e_status_e_leva_ao_cliente(auth_client, parcela_cora, settings):
    settings.CORA_PROVIDER = "log"
    cliente_pk = parcela_cora.contrato.cliente_id
    corpo = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()

    # a ação principal da linha é abrir o cliente; ligar e WhatsApp continuam à mão
    assert reverse("clientes:detalhe", args=[cliente_pk]) in corpo
    assert "Abrir cliente" in corpo
    assert 'href="tel:+5583999994444"' in corpo
    assert "wa.me" in corpo
    # baixa, cancelar/suspender cobrança e o diálogo de registrar foram para a tela do cliente
    assert reverse("pagamentos:novo", args=[parcela_cora.contrato_id]) not in corpo
    assert "dialog-registrar" not in corpo
    assert "Cancelar Pix" not in corpo
    assert "Suspender cobrança" not in corpo


@pytest.mark.django_db
def test_cobrar_hoje_sinaliza_cobranca_suspensa(auth_client, parcela_cora, settings):
    settings.CORA_PROVIDER = "log"
    CobrancaCora.objects.create(
        vencimento=parcela_cora, valor=Decimal("100.00"), data_vencimento=parcela_cora.data_vencimento,
        status=CobrancaCora.Status.CANCELADO,
    )
    corpo = auth_client.get(reverse("pagamentos:cobrar_hoje")).content.decode()
    assert "Suspensa" in corpo


@pytest.mark.django_db
def test_confirmacao_cora_da_baixa_automatica(parcela_cora, monkeypatch):
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_pago",
        status=CobrancaCora.Status.ABERTO,
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
    sincronizar_cobranca(cobranca)
    cobranca.refresh_from_db()
    assert cobranca.status == CobrancaCora.Status.PAGO
    pagamento = Pagamento.objects.get(vencimento=parcela_cora)
    assert pagamento.valor_pago == Decimal("100.00")
    assert pagamento.forma == Pagamento.Forma.PIX
    assert pagamento.usuario_baixa is None
    assert "inv_pago" in pagamento.observacao


@pytest.mark.django_db
def test_reconciliacao_processa_sinal_do_webhook(parcela_cora, monkeypatch):
    cobranca = CobrancaCora.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_sinal",
        status=CobrancaCora.Status.ABERTO,
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
    assert cobranca.cora_id == "inv_sinal"


@pytest.mark.django_db
def test_webhook_cora_so_registra_fatura_conhecida(client, parcela_cora, settings, monkeypatch):
    settings.CORA_WEBHOOK_TOKEN = "tok-cora"
    CobrancaCora.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_conhecida",
        status=CobrancaCora.Status.ABERTO,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda *args: pytest.fail("webhook público não pode consultar API autenticada"),
    )
    url = reverse("pagamentos:cora_webhook") + "?token=tok-cora"
    cabecalhos = {
        "webhook-event-type": "invoice.paid",
        "webhook-resource-id": "inv_conhecida",
    }
    primeira = client.post(url, headers=cabecalhos)
    segunda = client.post(url, headers=cabecalhos)
    assert primeira.status_code == segunda.status_code == 200
    assert EventoCora.objects.count() == 1


@pytest.mark.django_db
def test_webhook_cora_recusa_sem_token(client, settings):
    settings.CORA_WEBHOOK_TOKEN = "tok-cora"
    resposta = client.post(
        reverse("pagamentos:cora_webhook"),
        headers={"webhook-event-type": "invoice.paid", "webhook-resource-id": "x"},
    )
    assert resposta.status_code == 403
    assert EventoCora.objects.count() == 0


@pytest.mark.django_db
def test_painel_pix_exige_login(client):
    resposta = client.get(reverse("pagamentos:pix_painel"))
    assert resposta.status_code == 302


@pytest.mark.django_db
def test_painel_pix_mostra_pago_e_nao_pago(auth_client, parcela_cora):
    CobrancaCora.objects.create(
        vencimento=parcela_cora,
        cora_id="inv_atrasada",
        status=CobrancaCora.Status.VENCIDO,
        valor=Decimal("100.00"),
        data_vencimento=parcela_cora.data_vencimento,
    )
    resposta = auth_client.get(reverse("pagamentos:pix_painel"))
    assert resposta.status_code == 200
    assert "Não pago" in resposta.content.decode()


class _RespostaFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"ok": true}'


def test_abrir_repete_em_erro_transitorio_e_depois_funciona(monkeypatch, settings):
    settings.CORA_RETRY_TENTATIVAS = 3
    settings.CORA_RETRY_ESPERA_BASE_SEGUNDOS = 0
    chamadas = {"n": 0}

    def urlopen_falso(requisicao, context=None, timeout=None):
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            raise urllib.error.HTTPError(
                "https://cora.test", 503, "Service Unavailable", {}, io.BytesIO(b"fora do ar")
            )
        return _RespostaFalsa()

    monkeypatch.setattr(cora_api.urllib.request, "urlopen", urlopen_falso)
    resultado = cora_api._abrir(object(), contexto=None, autenticada=True)
    assert resultado == {"ok": True}
    assert chamadas["n"] == 3


def test_abrir_nao_repete_em_erro_definitivo_do_cliente(monkeypatch, settings):
    settings.CORA_RETRY_TENTATIVAS = 3
    settings.CORA_RETRY_ESPERA_BASE_SEGUNDOS = 0
    chamadas = {"n": 0}

    def urlopen_falso(requisicao, context=None, timeout=None):
        chamadas["n"] += 1
        raise urllib.error.HTTPError(
            "https://cora.test", 400, "Bad Request", {}, io.BytesIO(b"payload invalido")
        )

    monkeypatch.setattr(cora_api.urllib.request, "urlopen", urlopen_falso)
    with pytest.raises(cora_api.CoraErro):
        cora_api._abrir(object(), contexto=None, autenticada=True)
    assert chamadas["n"] == 1
