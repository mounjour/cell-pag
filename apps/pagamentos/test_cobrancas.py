import datetime
import hashlib
import hmac
import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.cobranca import dados_da_mensagem, processar_cobrancas
from apps.pagamentos.models import Cobranca, Vencimento


date = datetime.date


@pytest.fixture
def cliente_cobranca(db):
    cliente = Cliente.objects.create(
        nome="Maria da Silva",
        cpf=CPFGen().generate(),
        telefone_whatsapp="+5583999991234",
    )
    return cliente


def _contrato(cliente, hoje, *, atraso=0):
    contrato = Contrato.objects.create(
        cliente=cliente,
        apelido="iPhone 13",
        aparelho_modelo="iPhone 13",
        valor_total=Decimal("1000.00"),
        estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("100.00"),
        num_parcelas=10,
        data_inicio=hoje - datetime.timedelta(days=atraso + 1),
        proximo_vencimento=hoje - datetime.timedelta(days=atraso),
    )
    Vencimento.objects.create(
        contrato=contrato,
        numero=1,
        data_vencimento=hoje - datetime.timedelta(days=atraso),
        valor_previsto=Decimal("100.00"),
    )
    return contrato


@pytest.mark.django_db
def test_mensagem_de_vencimento(cliente_cobranca, settings):
    hoje = date(2026, 9, 4)
    _contrato(cliente_cobranca, hoje)
    from apps.pagamentos.agenda import montar_agenda_do_dia

    dados = dados_da_mensagem(montar_agenda_do_dia(hoje)["linhas"][0])
    assert dados["template"] == settings.WHATSAPP_TEMPLATE_VENCIMENTO
    assert "vence a parcela 1" in dados["mensagem"]


@pytest.mark.django_db
def test_mensagem_de_atraso_e_bloqueio(cliente_cobranca, settings):
    hoje = date(2026, 9, 10)
    contrato = _contrato(cliente_cobranca, hoje, atraso=2)
    from apps.pagamentos.agenda import montar_agenda_do_dia

    dados = dados_da_mensagem(montar_agenda_do_dia(hoje)["linhas"][0])
    assert dados["template"] == settings.WHATSAPP_TEMPLATE_ATRASO
    contrato.vencimentos.update(data_vencimento=hoje - datetime.timedelta(days=8))
    contrato.proximo_vencimento = hoje - datetime.timedelta(days=8)
    contrato.save(update_fields=["proximo_vencimento", "atualizado_em"])
    dados = dados_da_mensagem(montar_agenda_do_dia(hoje)["linhas"][0])
    assert dados["template"] == settings.WHATSAPP_TEMPLATE_BLOQUEIO
    assert "evitar o bloqueio" in dados["mensagem"]


@pytest.mark.django_db
def test_modo_log_cria_uma_unica_cobranca_pendente(cliente_cobranca, settings):
    settings.WHATSAPP_PROVIDER = "log"
    hoje = date(2026, 9, 4)
    _contrato(cliente_cobranca, hoje)
    primeiro = processar_cobrancas(hoje)
    segundo = processar_cobrancas(hoje)
    assert primeiro["simuladas"] == 1
    assert segundo["preparadas"] == 0
    assert Cobranca.objects.count() == 1
    assert Cobranca.objects.get().status == Cobranca.Status.PENDENTE


@pytest.mark.django_db
def test_envio_real_grava_id_e_nao_duplica(cliente_cobranca, settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "meta"
    hoje = date(2026, 9, 4)
    _contrato(cliente_cobranca, hoje)
    monkeypatch.setattr(
        "apps.pagamentos.cobranca.enviar_template",
        lambda **kwargs: {"simulado": False, "id": "wamid.123"},
    )
    primeiro = processar_cobrancas(hoje)
    segundo = processar_cobrancas(hoje)
    cobranca = Cobranca.objects.get()
    assert primeiro["enviadas"] == 1
    assert segundo["ignoradas"] == 1
    assert cobranca.status == Cobranca.Status.ENVIADO
    assert cobranca.id_externo == "wamid.123"


@pytest.mark.django_db
def test_comando_somente_prepara(cliente_cobranca):
    hoje = date(2026, 9, 4)
    _contrato(cliente_cobranca, hoje)
    saida = StringIO()
    call_command(
        "enviar_cobrancas_clientes",
        "--hoje",
        hoje.isoformat(),
        "--somente-preparar",
        stdout=saida,
    )
    assert Cobranca.objects.count() == 1
    assert "1 preparada" in saida.getvalue()


@pytest.mark.django_db
def test_webhook_verificacao(client, settings):
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "segredo-verificacao"
    resposta = client.get(
        reverse("pagamentos:whatsapp_webhook"),
        {"hub.mode": "subscribe", "hub.verify_token": "segredo-verificacao", "hub.challenge": "12345"},
    )
    assert resposta.status_code == 200
    assert resposta.content == b"12345"


@pytest.mark.django_db
def test_webhook_atualiza_entrega_com_assinatura(client, settings, cliente_cobranca):
    hoje = date(2026, 9, 4)
    contrato = _contrato(cliente_cobranca, hoje)
    cobranca = Cobranca.objects.create(
        contrato=contrato,
        vencimento=contrato.vencimentos.first(),
        data_alvo=hoje,
        destinatario="5583999991234",
        mensagem="Teste",
        status=Cobranca.Status.ENVIADO,
        id_externo="wamid.abc",
    )
    settings.WHATSAPP_APP_SECRET = "app-secret"
    payload = {
        "entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.abc", "status": "delivered", "timestamp": "1788541200"}]}}]}]
    }
    corpo = json.dumps(payload).encode()
    assinatura = "sha256=" + hmac.new(b"app-secret", corpo, hashlib.sha256).hexdigest()
    resposta = client.post(
        reverse("pagamentos:whatsapp_webhook"),
        data=corpo,
        content_type="application/json",
        headers={"X-Hub-Signature-256": assinatura},
    )
    assert resposta.status_code == 200
    cobranca.refresh_from_db()
    assert cobranca.status == Cobranca.Status.ENTREGUE
    assert cobranca.entregue_em is not None


@pytest.mark.django_db
def test_webhook_recusa_assinatura_invalida(client, settings):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    resposta = client.post(
        reverse("pagamentos:whatsapp_webhook"),
        data=b"{}",
        content_type="application/json",
        headers={"X-Hub-Signature-256": "sha256=errada"},
    )
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_webhook_nao_regride_status(client, settings, cliente_cobranca):
    hoje = date(2026, 9, 4)
    contrato = _contrato(cliente_cobranca, hoje)
    cobranca = Cobranca.objects.create(
        contrato=contrato,
        data_alvo=hoje,
        destinatario="5583999991234",
        mensagem="Teste",
        status=Cobranca.Status.LIDO,
        id_externo="wamid.lido",
    )
    settings.WHATSAPP_APP_SECRET = ""
    settings.DEBUG = True
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.lido", "status": "sent"}]}}]}]}
    resposta = client.post(
        reverse("pagamentos:whatsapp_webhook"),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resposta.status_code == 200
    cobranca.refresh_from_db()
    assert cobranca.status == Cobranca.Status.LIDO
