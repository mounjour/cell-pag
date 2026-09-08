"""Geração, conciliação e baixa automática das cobranças Pix da Cora."""

import datetime
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import cora_api
from .models import CobrancaCora, EventoCora, Pagamento, Vencimento


STATUS_CORA = {
    "DRAFT": CobrancaCora.Status.ABERTO,
    "INITIATED": CobrancaCora.Status.ABERTO,
    "IN_PAYMENT": CobrancaCora.Status.ABERTO,
    "OPEN": CobrancaCora.Status.ABERTO,
    "LATE": CobrancaCora.Status.VENCIDO,
    "PAID": CobrancaCora.Status.PAGO,
    "CANCELLED": CobrancaCora.Status.CANCELADO,
    "CANCELED": CobrancaCora.Status.CANCELADO,
}

# Formas de pagamento pedidas na fatura. Boleto e cartão ficam de fora por
# decisão do projeto (Alisson) — as cobranças são feitas só em Pix.
FORMAS_PAGAMENTO = ["PIX"]


def obter_ou_criar_cobranca(vencimento: Vencimento, hoje=None) -> CobrancaCora:
    hoje = hoje or timezone.localdate()
    cobranca, _ = CobrancaCora.objects.get_or_create(
        vencimento=vencimento,
        defaults={
            "valor": max(vencimento.saldo, Decimal("0.00")),
            "data_vencimento": vencimento.data_vencimento,
        },
    )
    if cobranca.cora_id or settings.CORA_PROVIDER == "log":
        return cobranca
    if settings.CORA_PROVIDER != "cora":
        cobranca.status = CobrancaCora.Status.ERRO
        cobranca.erro = f"CORA_PROVIDER desconhecido: {settings.CORA_PROVIDER!r}"
        cobranca.save(update_fields=["status", "erro", "atualizado_em"])
        return cobranca

    contrato = vencimento.contrato
    payload = {
        "code": f"vencimento-{vencimento.pk}",
        "customer": {
            "name": contrato.cliente.nome[:60],
            "document": {"identity": contrato.cliente.cpf, "type": "CPF"},
        },
        "services": [
            {
                "name": f"Parcela {vencimento.numero}"[:60],
                "description": f"{contrato.apelido} - parcela {vencimento.numero}"[:100],
                "amount": int(cobranca.valor * 100),
            }
        ],
        "payment_forms": FORMAS_PAGAMENTO,
        # A Cora não aceita criação já vencida. O vencimento original segue no
        # nosso banco e o QR recuperado recebe prazo até hoje quando necessário.
        "payment_terms": {"due_date": max(vencimento.data_vencimento, hoje).isoformat()},
    }
    try:
        resposta = cora_api.criar_fatura(payload, cobranca.idempotency_key)
        _aplicar_resposta(cobranca, resposta)
    except cora_api.CoraErro as exc:
        cobranca.status = CobrancaCora.Status.ERRO
        cobranca.erro = str(exc)
        cobranca.save(update_fields=["status", "erro", "atualizado_em"])
    return cobranca


def sincronizar_cobranca(cobranca: CobrancaCora) -> CobrancaCora:
    if not cobranca.cora_id:
        return cobranca
    resposta = cora_api.consultar_fatura(cobranca.cora_id)
    _aplicar_resposta(cobranca, resposta)
    return cobranca


@transaction.atomic
def _aplicar_resposta(cobranca: CobrancaCora, resposta: dict) -> None:
    status = STATUS_CORA.get(str(resposta.get("status", "")).upper())
    if not status:
        raise cora_api.CoraErro(f"Status de fatura desconhecido: {resposta.get('status')!r}")
    pix = resposta.get("pix") or (resposta.get("payment_options") or {}).get("pix") or {}

    cobranca.cora_id = resposta.get("id") or cobranca.cora_id
    cobranca.status = status
    cobranca.total_pago = Decimal(resposta.get("total_paid", 0)) / 100
    cobranca.pix_copia_e_cola = pix.get("emv", cobranca.pix_copia_e_cola)
    cobranca.qr_code_url = pix.get("url") or cobranca.qr_code_url
    cobranca.erro = ""
    if status == CobrancaCora.Status.PAGO:
        ocorrencia = resposta.get("occurrence_date")
        if ocorrencia:
            try:
                cobranca.pago_em = timezone.make_aware(
                    datetime.datetime.fromisoformat(ocorrencia.replace("Z", "+00:00")).replace(tzinfo=None)
                )
            except ValueError:
                cobranca.pago_em = timezone.now()
        else:
            cobranca.pago_em = timezone.now()
    cobranca.save()
    if status == CobrancaCora.Status.PAGO and cobranca.total_pago > 0:
        _dar_baixa(cobranca)


def _dar_baixa(cobranca: CobrancaCora) -> None:
    if Pagamento.objects.filter(vencimento=cobranca.vencimento).exists():
        return
    Pagamento(
        contrato=cobranca.vencimento.contrato,
        vencimento=cobranca.vencimento,
        data_pagamento=(cobranca.pago_em or timezone.now()).date(),
        valor_pago=cobranca.total_pago,
        forma=Pagamento.Forma.PIX,
        observacao=f"Baixa automática pela Cora ({cobranca.cora_id}).",
    ).registrar()


def reconciliar_abertas() -> dict:
    resultado = {"consultadas": 0, "pagas": 0, "erros": 0}
    for cobranca in CobrancaCora.objects.filter(
        status__in=[CobrancaCora.Status.ABERTO, CobrancaCora.Status.VENCIDO]
    ).exclude(cora_id__isnull=True).exclude(cora_id=""):
        try:
            sincronizar_cobranca(cobranca)
            resultado["consultadas"] += 1
            EventoCora.objects.filter(
                recurso_id=cobranca.cora_id,
                processado=False,
            ).update(processado=True, erro="", processado_em=timezone.now())
            if cobranca.status == CobrancaCora.Status.PAGO:
                resultado["pagas"] += 1
        except cora_api.CoraErro as exc:
            cobranca.erro = str(exc)
            cobranca.save(update_fields=["erro", "atualizado_em"])
            resultado["erros"] += 1
    return resultado
