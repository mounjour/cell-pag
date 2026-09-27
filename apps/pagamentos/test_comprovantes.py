"""Comprovante enviado pelo cliente por WhatsApp + confirmação de pagamento."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos import cora_api
from apps.pagamentos.models import CobrancaCora, ComprovanteRecebido, Pagamento, Vencimento
from apps.pagamentos.pix_cora import sincronizar_cobranca
from apps.pagamentos.whatsapp import WhatsAppErro

date = datetime.date
NUMERO = "5583999996666"


@pytest.fixture
def parcela(db):
    cliente = Cliente.objects.create(
        nome="joana d'arc silva", cpf="52998224725", telefone_whatsapp=f"+{NUMERO}"
    )
    contrato = Contrato.objects.create(
        cliente=cliente, apelido="Moto", aparelho_modelo="Moto G", valor_total=Decimal("500.00"),
        estrutura=Contrato.Estrutura.MENSAL, valor_parcela=Decimal("100.00"), num_parcelas=5,
        data_inicio=date(2026, 8, 4), proximo_vencimento=date(2026, 9, 4),
    )
    return Vencimento.objects.create(
        contrato=contrato, numero=1, data_vencimento=date(2026, 9, 4), valor_previsto=Decimal("100.00")
    )


@pytest.fixture
def pix(parcela):
    return CobrancaCora.objects.create(
        vencimento=parcela, cora_id="inv_c1", status=CobrancaCora.Status.ABERTO, valor=Decimal("100.00"),
        data_vencimento=parcela.data_vencimento, pix_copia_e_cola="00020126PIX",
    )


@pytest.fixture
def enviadas(monkeypatch):
    """WhatsApp de mentira: guarda (destinatário, texto) de cada mensagem enviada."""
    lista = []

    def enviar(*, destinatario, texto):
        lista.append((destinatario, texto))
        return {"simulado": False, "id": f"OUT-{len(lista)}"}

    monkeypatch.setattr("apps.pagamentos.comprovantes.enviar_mensagem", enviar)
    return lista


@pytest.fixture
def cora(monkeypatch):
    """Cora de mentira: `estado["status"]` controla o que a consulta devolve."""
    estado = {"status": "OPEN", "total_paid": 0}
    monkeypatch.setattr(
        "apps.pagamentos.cora_api.consultar_fatura",
        lambda cora_id: {
            "id": cora_id, "status": estado["status"], "total_paid": estado["total_paid"],
            "occurrence_date": "2026-09-11T10:00:00Z",
        },
    )
    return estado


def _msg(*, id="MSG1", jid=f"{NUMERO}@s.whatsapp.net", de_mim=False, message=None):
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": jid, "fromMe": de_mim, "id": id},
            "message": message if message is not None else {"imageMessage": {"caption": "paguei", "mimetype": "image/jpeg"}},
        },
    }


def _receber(client, settings, payload):
    settings.EVOLUTION_WEBHOOK_TOKEN = "tok"
    return client.post(
        reverse("pagamentos:whatsapp_webhook"), payload, content_type="application/json", headers={"apikey": "tok"}
    )


# ---------- Chegada do arquivo ----------

@pytest.mark.django_db
def test_imagem_de_cliente_com_pix_nao_pago_vira_aviso_e_o_cliente_recebe_resposta(client, settings, parcela, pix, cora, enviadas):
    resp = _receber(client, settings, _msg())
    assert resp.status_code == 200 and resp.json()["comprovantes"] == 1
    c = ComprovanteRecebido.objects.get()
    assert c.status == ComprovanteRecebido.Status.AGUARDANDO
    assert c.vencimento == parcela and c.tipo == "imagem" and c.legenda == "paguei"
    assert len(enviadas) == 1
    assert enviadas[0][0] == NUMERO
    assert "Joana" in enviadas[0][1] and "Ainda não identificamos esse Pix" in enviadas[0][1]
    assert c.resposta_enviada_em is not None


@pytest.mark.django_db
def test_pdf_e_reconhecido_com_o_nome_do_arquivo(client, settings, parcela, pix, cora, enviadas):
    _receber(client, settings, _msg(message={"documentMessage": {"mimetype": "application/pdf", "fileName": "comprovante.pdf"}}))
    c = ComprovanteRecebido.objects.get()
    assert c.tipo == "documento" and c.nome_arquivo == "comprovante.pdf"


@pytest.mark.django_db
def test_pdf_com_legenda_aninhada_tambem_vale(client, settings, parcela, pix, cora, enviadas):
    aninhado = {"documentWithCaptionMessage": {"message": {"documentMessage": {
        "mimetype": "application/pdf", "fileName": "pix.pdf", "caption": "segue"}}}}
    _receber(client, settings, _msg(message=aninhado))
    assert ComprovanteRecebido.objects.get().legenda == "segue"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    _msg(message={"conversation": "oi, tudo bem?"}),                                   # texto
    _msg(message={"audioMessage": {"mimetype": "audio/ogg"}}),                        # áudio
    _msg(message={"stickerMessage": {}}),                                             # figurinha
    _msg(message={"documentMessage": {"mimetype": "application/msword", "fileName": "a.doc"}}),  # não é PDF/imagem
    _msg(de_mim=True),                                                                # mensagem nossa
    _msg(jid="120363000000@g.us"),                                                    # grupo
    _msg(jid="98765432101234@lid"),                                                   # id anônimo, sem número
    _msg(jid="5511900000000@s.whatsapp.net"),                                         # número que não é de cliente
], ids=["texto", "audio", "figurinha", "doc-word", "de-mim", "grupo", "lid", "desconhecido"])
def test_o_que_nao_e_arquivo_de_cliente_e_ignorado(client, settings, parcela, pix, cora, enviadas, payload):
    resp = _receber(client, settings, payload)
    assert resp.status_code == 200 and resp.json()["comprovantes"] == 0
    assert not ComprovanteRecebido.objects.exists() and enviadas == []


@pytest.mark.django_db
def test_numero_sem_o_nono_digito_ainda_acha_o_cliente(client, settings, parcela, pix, cora, enviadas):
    sem_nove = "558399996666"  # o WhatsApp às vezes omite o 9
    _receber(client, settings, _msg(jid=f"{sem_nove}@s.whatsapp.net"))
    assert ComprovanteRecebido.objects.get().cliente == parcela.contrato.cliente


@pytest.mark.django_db
def test_aviso_repetido_pela_evolution_nao_duplica_nem_responde_duas_vezes(client, settings, parcela, pix, cora, enviadas):
    _receber(client, settings, _msg())
    _receber(client, settings, _msg())
    assert ComprovanteRecebido.objects.count() == 1 and len(enviadas) == 1


@pytest.mark.django_db
def test_segundo_arquivo_em_seguida_nao_gera_outra_resposta(client, settings, parcela, pix, cora, enviadas):
    _receber(client, settings, _msg(id="A"))
    _receber(client, settings, _msg(id="B"))
    assert ComprovanteRecebido.objects.count() == 2 and len(enviadas) == 1


@pytest.mark.django_db
def test_falha_ao_responder_nao_derruba_o_aviso(client, settings, parcela, pix, cora, monkeypatch):
    def cai(**_):
        raise WhatsAppErro("Evolution fora do ar")

    monkeypatch.setattr("apps.pagamentos.comprovantes.enviar_mensagem", cai)
    resp = _receber(client, settings, _msg())
    assert resp.status_code == 200
    c = ComprovanteRecebido.objects.get()
    assert c.status == ComprovanteRecebido.Status.AGUARDANDO and c.resposta_enviada_em is None


@pytest.mark.django_db
def test_cliente_sem_parcela_em_aberto_ainda_gera_aviso_sem_parcela(client, settings, parcela, cora, enviadas):
    parcela.status = Vencimento.Status.PAGO
    parcela.save()
    _receber(client, settings, _msg())
    assert ComprovanteRecebido.objects.get().vencimento is None


# ---------- Pix confirmado ----------

@pytest.mark.django_db
def test_pix_ja_pago_quando_o_arquivo_chega_confirma_na_hora(client, settings, parcela, pix, cora, enviadas, django_capture_on_commit_callbacks):
    cora.update(status="PAID", total_paid=10000)
    with django_capture_on_commit_callbacks(execute=True):
        _receber(client, settings, _msg())
    c = ComprovanteRecebido.objects.get()
    assert c.status == ComprovanteRecebido.Status.CONFIRMADO
    assert Pagamento.objects.get(vencimento=parcela).observacao.startswith("Baixa automática pela Cora")
    textos = [t for _, t in enviadas]
    assert len(textos) == 1 and "Recebemos o seu pagamento de R$ 100,00" in textos[0]  # só a confirmação
    assert not any("Ainda não identificamos" in t for t in textos)


@pytest.mark.django_db
def test_todo_pix_confirmado_manda_confirmacao_uma_unica_vez(parcela, pix, cora, enviadas, django_capture_on_commit_callbacks):
    cora.update(status="PAID", total_paid=10000)
    with django_capture_on_commit_callbacks(execute=True):
        sincronizar_cobranca(pix)
    with django_capture_on_commit_callbacks(execute=True):
        sincronizar_cobranca(pix)  # aviso repetido da Cora
    assert len(enviadas) == 1
    destino, texto = enviadas[0]
    assert destino == NUMERO
    assert texto == "Olá, Joana! Recebemos o seu pagamento de R$ 100,00 (parcela 1 — Moto). Obrigado!"
    pix.refresh_from_db()
    assert pix.confirmacao_enviada_em is not None


@pytest.mark.django_db
def test_aviso_pendente_e_resolvido_quando_o_pix_cai_depois(client, settings, parcela, pix, cora, enviadas, django_capture_on_commit_callbacks):
    _receber(client, settings, _msg())                      # Pix ainda não caiu
    assert ComprovanteRecebido.objects.get().status == ComprovanteRecebido.Status.AGUARDANDO
    cora.update(status="PAID", total_paid=10000)            # minutos depois, cai
    with django_capture_on_commit_callbacks(execute=True):
        sincronizar_cobranca(pix)
    assert ComprovanteRecebido.objects.get().status == ComprovanteRecebido.Status.CONFIRMADO
    assert "Recebemos o seu pagamento" in enviadas[-1][1]


@pytest.mark.django_db
def test_falha_ao_confirmar_nao_desfaz_a_baixa_e_tenta_de_novo_depois(parcela, pix, cora, monkeypatch, django_capture_on_commit_callbacks):
    def cai(**_):
        raise WhatsAppErro("Evolution fora do ar")

    monkeypatch.setattr("apps.pagamentos.comprovantes.enviar_mensagem", cai)
    cora.update(status="PAID", total_paid=10000)
    with django_capture_on_commit_callbacks(execute=True):
        sincronizar_cobranca(pix)
    pix.refresh_from_db()
    assert Pagamento.objects.filter(vencimento=parcela).exists()      # a baixa vale
    assert pix.confirmacao_enviada_em is None                          # ficou pendente

    from apps.pagamentos.comprovantes import enviar_confirmacao

    enviadas = []
    monkeypatch.setattr(
        "apps.pagamentos.comprovantes.enviar_mensagem",
        lambda *, destinatario, texto: enviadas.append(texto) or {"simulado": False, "id": "X"},
    )
    assert enviar_confirmacao(pix.pk) is True and len(enviadas) == 1


@pytest.mark.django_db
def test_pix_pago_em_duplicidade_nao_manda_confirmacao(parcela, pix, cora, enviadas, django_capture_on_commit_callbacks):
    Pagamento(
        contrato=parcela.contrato, vencimento=parcela, data_pagamento=date(2026, 9, 10),
        valor_pago=Decimal("100.00"), forma=Pagamento.Forma.DINHEIRO,
    ).registrar()
    cora.update(status="PAID", total_paid=10000)
    with django_capture_on_commit_callbacks(execute=True):
        sincronizar_cobranca(pix)
    pix.refresh_from_db()
    assert pix.duplicada is True and enviadas == []


@pytest.mark.django_db
def test_modo_simulacao_nao_marca_confirmacao_como_enviada(parcela, pix, cora, settings, django_capture_on_commit_callbacks):
    settings.WHATSAPP_PROVIDER = "log"
    cora.update(status="PAID", total_paid=10000)
    with django_capture_on_commit_callbacks(execute=True):
        sincronizar_cobranca(pix)
    pix.refresh_from_db()
    assert pix.confirmacao_enviada_em is None


# ---------- Telas do financeiro ----------

def _avisos(resp):
    return [(m.level_tag, str(m)) for m in get_messages(resp.wsgi_request)]


@pytest.fixture
def aviso(parcela, pix):
    return ComprovanteRecebido.objects.create(
        cliente=parcela.contrato.cliente, vencimento=parcela, id_externo="X1", tipo="imagem", legenda="paguei",
    )


@pytest.mark.django_db
def test_painel_pix_lista_o_aviso_e_o_menu_mostra_o_selo(auth_client, aviso):
    html = auth_client.get(reverse("pagamentos:pix_painel")).content.decode()
    assert "Comprovantes recebidos" in html and "joana d&#x27;arc silva" in html
    assert "não prova o pagamento" in html and "Abrir WhatsApp" in html
    assert 'class="selo selo--alerta"' in html


@pytest.mark.django_db
def test_conferir_com_pix_ainda_aberto_avisa_que_nao_caiu(auth_client, aviso, cora):
    resp = auth_client.post(reverse("pagamentos:comprovante_conferir", args=[aviso.pk]))
    assert resp.status_code == 302
    assert any(n == "warning" and "ainda não caiu" in t for n, t in _avisos(resp))
    aviso.refresh_from_db()
    assert aviso.status == ComprovanteRecebido.Status.AGUARDANDO


@pytest.mark.django_db
def test_conferir_com_pix_pago_da_baixa_e_confirma(auth_client, aviso, cora, enviadas, django_capture_on_commit_callbacks):
    cora.update(status="PAID", total_paid=10000)
    with django_capture_on_commit_callbacks(execute=True):
        resp = auth_client.post(reverse("pagamentos:comprovante_conferir", args=[aviso.pk]))
    aviso.refresh_from_db()
    assert aviso.status == ComprovanteRecebido.Status.CONFIRMADO
    assert any(n == "success" and "confirmado pela Cora" in t for n, t in _avisos(resp))
    assert len(enviadas) == 1


@pytest.mark.django_db
def test_conferir_com_cora_fora_do_ar_avisa(auth_client, aviso, monkeypatch):
    def cai(cora_id):
        raise cora_api.CoraErro("timeout")

    monkeypatch.setattr("apps.pagamentos.cora_api.consultar_fatura", cai)
    resp = auth_client.post(reverse("pagamentos:comprovante_conferir", args=[aviso.pk]))
    assert any(n == "warning" and "Não consegui consultar a Cora" in t for n, t in _avisos(resp))


@pytest.mark.django_db
def test_descartar_tira_o_aviso_e_o_selo(auth_client, aviso, operador):
    resp = auth_client.post(reverse("pagamentos:comprovante_descartar", args=[aviso.pk]))
    assert resp.status_code == 302
    aviso.refresh_from_db()
    assert aviso.status == ComprovanteRecebido.Status.DESCARTADO and aviso.resolvido_por == operador
    html = auth_client.get(reverse("pagamentos:pix_painel")).content.decode()
    assert "Comprovantes recebidos" not in html and 'selo--alerta"' not in html


@pytest.mark.django_db
def test_acoes_do_comprovante_exigem_login_e_post(auth_client, aviso):
    from django.test import Client

    for nome in ("comprovante_conferir", "comprovante_descartar"):
        url = reverse(f"pagamentos:{nome}", args=[aviso.pk])
        resp = Client().post(url)
        assert resp.status_code == 302 and "/entrar/" in resp.url
        assert auth_client.get(url).status_code == 405
    aviso.refresh_from_db()
    assert aviso.status == ComprovanteRecebido.Status.AGUARDANDO
