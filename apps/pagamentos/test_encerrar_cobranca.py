"""Parcela paga por outro meio (dinheiro etc.): Pix cancelado, mensagem apagada e
Pix pago em duplicidade sinalizado."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos import cora_api, whatsapp
from apps.pagamentos.models import Cobranca, CobrancaCora, Pagamento, Vencimento
from apps.pagamentos.pix_cora import sincronizar_cobranca

date = datetime.date


@pytest.fixture
def parcela(db):
    cliente = Cliente.objects.create(
        nome="Cliente Dinheiro", cpf=CPFGen().generate(), telefone_whatsapp="+5583999995555"
    )
    contrato = Contrato.objects.create(
        cliente=cliente, apelido="Moto G", aparelho_modelo="Moto G", valor_total=Decimal("500.00"),
        estrutura=Contrato.Estrutura.MENSAL, valor_parcela=Decimal("100.00"), num_parcelas=5,
        data_inicio=date(2026, 8, 4), proximo_vencimento=date(2026, 9, 4),
    )
    return Vencimento.objects.create(
        contrato=contrato, numero=1, data_vencimento=date(2026, 9, 4), valor_previsto=Decimal("100.00")
    )


def _pix(parcela, status=CobrancaCora.Status.ABERTO):
    return CobrancaCora.objects.create(
        vencimento=parcela, cora_id="inv_1", status=status, valor=Decimal("100.00"),
        data_vencimento=parcela.data_vencimento, pix_copia_e_cola="00020126PIX", qr_code_url="https://x/qr.png",
    )


def _mensagem(parcela, *, status=Cobranca.Status.ENTREGUE, horas_atras=2, dia=0):
    return Cobranca.objects.create(
        contrato=parcela.contrato, vencimento=parcela, data_alvo=date(2026, 9, 10) + datetime.timedelta(days=dia),
        destinatario="5583999995555", mensagem="Sua parcela venceu", status=status,
        id_externo="MSG-PRINCIPAL", id_externo_codigo="MSG-CODIGO",
        enviado_em=timezone.now() - datetime.timedelta(hours=horas_atras),
    )


def _pagar_em_dinheiro(client, parcela):
    return client.post(
        reverse("pagamentos:novo", args=[parcela.contrato.pk]),
        {
            "vencimento": parcela.pk, "data_pagamento": "2026-09-10", "valor_pago": "100,00",
            "juros_pago": "", "forma": Pagamento.Forma.DINHEIRO, "observacao": "",
        },
    )


def _avisos(resp):
    return [(m.level_tag, str(m)) for m in get_messages(resp.wsgi_request)]


@pytest.fixture
def fake_cora(settings, monkeypatch):
    """Cora de mentira: guarda o estado da fatura; cancelar leva a CANCELLED."""
    settings.CORA_PROVIDER = "cora"
    estado = {"status": "OPEN", "total_paid": 0, "canceladas": []}
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": estado["status"], "total_paid": estado["total_paid"]},
    )

    def cancelar(cora_id):
        estado["canceladas"].append(cora_id)
        estado["status"] = "CANCELLED"
        return {}

    monkeypatch.setattr("apps.pagamentos.cora_api.cancelar_fatura", cancelar)
    return estado


@pytest.fixture
def fake_whatsapp(settings, monkeypatch):
    """Evolution de mentira: registra as mensagens apagadas; `falhar` simula recusa."""
    settings.WHATSAPP_PROVIDER = "evolution"
    estado = {"apagadas": [], "falhar": False}

    def apagar(*, destinatario, id_mensagem):
        if estado["falhar"]:
            raise whatsapp.WhatsAppErro("A Evolution recusou a operação (HTTP 400).")
        estado["apagadas"].append(id_mensagem)
        return {"simulado": False}

    monkeypatch.setattr("apps.pagamentos.limpeza.apagar_mensagem", apagar)
    return estado


# ---------- Cliente Evolution ----------

def test_apagar_mensagem_chama_delete_com_id_e_jid(settings, monkeypatch):
    settings.WHATSAPP_PROVIDER = "evolution"
    chamadas = []
    monkeypatch.setattr(
        whatsapp, "_chamar_evolution", lambda caminho, corpo, metodo="POST": chamadas.append((caminho, corpo, metodo)) or {}
    )
    whatsapp.apagar_mensagem(destinatario="+55 83 99999-5555", id_mensagem="ABC")
    assert chamadas == [(
        "/chat/deleteMessageForEveryone",
        {"id": "ABC", "remoteJid": "5583999995555@s.whatsapp.net", "fromMe": True},
        "DELETE",
    )]


def test_apagar_mensagem_em_modo_log_nao_chama_ninguem(settings):
    settings.WHATSAPP_PROVIDER = "log"
    assert whatsapp.apagar_mensagem(destinatario="5583999995555", id_mensagem="ABC") == {"simulado": True}


# ---------- Pagamento manual: Pix ----------

@pytest.mark.django_db
def test_pagar_em_dinheiro_cancela_o_pix_em_aberto(auth_client, parcela, fake_cora):
    pix = _pix(parcela)
    resp = _pagar_em_dinheiro(auth_client, parcela)
    assert resp.status_code == 302
    pix.refresh_from_db()
    assert pix.status == CobrancaCora.Status.CANCELADO and pix.pix_copia_e_cola == ""
    assert fake_cora["canceladas"] == ["inv_1"]
    assert Pagamento.objects.get(vencimento=parcela).forma == Pagamento.Forma.DINHEIRO
    assert any("Pix da parcela 1 cancelado" in t for _, t in _avisos(resp))


@pytest.mark.django_db
def test_sem_pix_nada_a_cancelar_e_o_pagamento_segue(auth_client, parcela):
    resp = _pagar_em_dinheiro(auth_client, parcela)
    assert resp.status_code == 302
    assert Pagamento.objects.filter(vencimento=parcela).count() == 1
    assert not any("Pix" in t for _, t in _avisos(resp))


@pytest.mark.django_db
def test_cora_fora_do_ar_registra_o_pagamento_e_avisa_para_cancelar_a_mao(auth_client, parcela, fake_cora, monkeypatch):
    pix = _pix(parcela)

    def cai(cora_id):
        raise cora_api.CoraErro("timeout")

    monkeypatch.setattr("apps.pagamentos.cora_api.consultar_fatura", cai)
    resp = _pagar_em_dinheiro(auth_client, parcela)
    assert Pagamento.objects.filter(vencimento=parcela).exists()        # o pagamento vale
    pix.refresh_from_db()
    assert pix.status == CobrancaCora.Status.ABERTO                     # nada mudou no Pix
    assert any(n == "warning" and "Cancele-o no painel Pix" in t for n, t in _avisos(resp))


@pytest.mark.django_db
def test_pix_ja_pago_na_hora_do_pagamento_vira_duplicidade(auth_client, parcela, fake_cora):
    pix = _pix(parcela)
    fake_cora.update(status="PAID", total_paid=10000)                  # a Cora diz: já foi pago
    resp = _pagar_em_dinheiro(auth_client, parcela)
    pix.refresh_from_db()
    assert pix.duplicada is True and pix.duplicidade_resolvida_em is None
    assert Pagamento.objects.filter(vencimento=parcela).count() == 1    # sem 2ª baixa
    assert any(n == "warning" and "também pagou o Pix" in t for n, t in _avisos(resp))


# ---------- Pagamento manual: mensagens ----------

@pytest.mark.django_db
def test_mensagem_enviada_e_apagada_dos_dois_envios(auth_client, parcela, fake_whatsapp):
    msg = _mensagem(parcela)
    resp = _pagar_em_dinheiro(auth_client, parcela)
    msg.refresh_from_db()
    assert msg.status == Cobranca.Status.APAGADO
    assert sorted(fake_whatsapp["apagadas"]) == ["MSG-CODIGO", "MSG-PRINCIPAL"]  # imagem/legenda e copia-e-cola
    assert any("apagada do WhatsApp" in t for _, t in _avisos(resp))


@pytest.mark.django_db
def test_mensagem_pendente_e_cancelada_sem_chamar_o_whatsapp(auth_client, parcela, fake_whatsapp):
    msg = Cobranca.objects.create(
        contrato=parcela.contrato, vencimento=parcela, data_alvo=date(2026, 9, 10),
        destinatario="5583999995555", mensagem="x", status=Cobranca.Status.PENDENTE,
    )
    _pagar_em_dinheiro(auth_client, parcela)
    msg.refresh_from_db()
    assert msg.status == Cobranca.Status.CANCELADO and fake_whatsapp["apagadas"] == []


@pytest.mark.django_db
def test_mensagem_fora_da_janela_nao_e_tocada(auth_client, parcela, fake_whatsapp):
    msg = _mensagem(parcela, horas_atras=72)
    resp = _pagar_em_dinheiro(auth_client, parcela)
    msg.refresh_from_db()
    assert msg.status == Cobranca.Status.ENTREGUE and fake_whatsapp["apagadas"] == []
    assert not any("mensagem de cobrança" in t for _, t in _avisos(resp))


@pytest.mark.django_db
def test_falha_ao_apagar_avisa_para_avisar_o_cliente(auth_client, parcela, fake_whatsapp):
    fake_whatsapp["falhar"] = True
    msg = _mensagem(parcela)
    resp = _pagar_em_dinheiro(auth_client, parcela)
    msg.refresh_from_db()
    assert msg.status == Cobranca.Status.ENTREGUE                       # continua como estava
    assert Pagamento.objects.filter(vencimento=parcela).exists()        # o pagamento vale
    assert any(n == "warning" and "Cliente Dinheiro" in t and "ignorada" in t for n, t in _avisos(resp))


@pytest.mark.django_db
def test_apagar_desligado_so_avisa(auth_client, parcela, fake_whatsapp, settings):
    settings.WHATSAPP_APAGAR_AO_BAIXAR = False
    msg = _mensagem(parcela)
    resp = _pagar_em_dinheiro(auth_client, parcela)
    msg.refresh_from_db()
    assert fake_whatsapp["apagadas"] == [] and msg.status == Cobranca.Status.ENTREGUE
    assert any(n == "warning" and "desligada" in t for n, t in _avisos(resp))


@pytest.mark.django_db
def test_aviso_de_entrega_atrasado_nao_reabre_mensagem_apagada(client, parcela, settings):
    settings.EVOLUTION_WEBHOOK_TOKEN = "tok"
    msg = _mensagem(parcela, status=Cobranca.Status.APAGADO)
    resp = client.post(
        reverse("pagamentos:whatsapp_webhook"),
        {"event": "messages.update", "data": {"keyId": msg.id_externo, "status": "READ"}},
        content_type="application/json",
        headers={"apikey": "tok"},
    )
    msg.refresh_from_db()
    assert resp.status_code == 200 and resp.json()["atualizadas"] == 0
    assert msg.status == Cobranca.Status.APAGADO and msg.lido_em is None


# ---------- Duplicidade (Pix pago depois do dinheiro) ----------

@pytest.mark.django_db
def test_pix_pago_depois_do_dinheiro_e_sinalizado_e_nao_baixa_de_novo(parcela, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    Pagamento(
        contrato=parcela.contrato, vencimento=parcela, data_pagamento=date(2026, 9, 10),
        valor_pago=Decimal("100.00"), forma=Pagamento.Forma.DINHEIRO,
    ).registrar()
    pix = _pix(parcela)
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "PAID", "total_paid": 10000, "occurrence_date": "2026-09-11T10:00:00Z"},
    )
    sincronizar_cobranca(pix)
    sincronizar_cobranca(pix)  # repetição do aviso não muda nada
    pix.refresh_from_db()
    assert pix.duplicada is True
    assert Pagamento.objects.filter(vencimento=parcela).count() == 1


@pytest.mark.django_db
def test_pix_pago_normal_nao_e_duplicidade(parcela, settings, monkeypatch):
    settings.CORA_PROVIDER = "cora"
    pix = _pix(parcela)
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {"id": cora_id, "status": "PAID", "total_paid": 10000},
    )
    sincronizar_cobranca(pix)
    sincronizar_cobranca(pix)  # o aviso repetido da Cora não pode virar "duplicidade"
    pix.refresh_from_db()
    assert pix.duplicada is False
    assert Pagamento.objects.get(vencimento=parcela).observacao.startswith("Baixa automática pela Cora")


@pytest.mark.django_db
def test_painel_pix_mostra_duplicidade_e_selo_no_menu_e_resolve(auth_client, parcela):
    pix = _pix(parcela, status=CobrancaCora.Status.PAGO)
    pix.duplicada, pix.total_pago, pix.pago_em = True, Decimal("100.00"), timezone.now()
    pix.save()
    html = auth_client.get(reverse("pagamentos:pix_painel")).content.decode()
    assert "Pix recebido · revisão manual" in html and "Cliente Dinheiro" in html and "R$ 100,00" in html
    assert 'class="selo selo--alerta"><span' in html

    resp = auth_client.post(reverse("pagamentos:pix_duplicidade_resolvida", args=[pix.pk]))
    assert resp.status_code == 302
    pix.refresh_from_db()
    assert pix.duplicidade_resolvida_em is not None
    html = auth_client.get(reverse("pagamentos:pix_painel")).content.decode()
    assert "Pix recebido · revisão manual" not in html and 'class="selo selo--alerta"><span' not in html


@pytest.mark.django_db
def test_resolver_duplicidade_exige_login_e_post(auth_client, parcela):
    from django.test import Client

    pix = _pix(parcela, status=CobrancaCora.Status.PAGO)
    pix.duplicada = True
    pix.save()
    url = reverse("pagamentos:pix_duplicidade_resolvida", args=[pix.pk])
    anonimo = Client()  # `client` e `auth_client` são o mesmo objeto (já logado)
    resp = anonimo.post(url)
    assert resp.status_code == 302 and "/entrar/" in resp.url
    pix.refresh_from_db()
    assert pix.duplicidade_resolvida_em is None
    assert auth_client.get(url).status_code == 405
