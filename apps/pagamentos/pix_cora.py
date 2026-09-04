"""Geração, conciliação e baixa automática de cobranças Pix Cora."""

import datetime
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import cora_api
from .models import CobrancaPix, EventoCora, Pagamento, Vencimento


STATUS_CORA = {
    "DRAFT": CobrancaPix.Status.ABERTO,
    "INITIATED": CobrancaPix.Status.ABERTO,
    "IN_PAYMENT": CobrancaPix.Status.ABERTO,
    "OPEN": CobrancaPix.Status.ABERTO,
    "LATE": CobrancaPix.Status.VENCIDO,
    "PAID": CobrancaPix.Status.PAGO,
    "CANCELLED": CobrancaPix.Status.CANCELADO,
    "CANCELED": CobrancaPix.Status.CANCELADO,
}


def obter_ou_criar_pix(vencimento: Vencimento, hoje=None) -> CobrancaPix:
    hoje = hoje or timezone.localdate()
    pix, _ = CobrancaPix.objects.get_or_create(
        vencimento=vencimento,
        defaults={
            "valor": max(vencimento.saldo, Decimal("0.00")),
            "data_vencimento": vencimento.data_vencimento,
        },
    )
    if pix.cora_id or settings.CORA_PROVIDER == "log":
        return pix
    if settings.CORA_PROVIDER != "cora":
        pix.status = CobrancaPix.Status.ERRO
        pix.erro = f"CORA_PROVIDER desconhecido: {settings.CORA_PROVIDER!r}"
        pix.save(update_fields=["status", "erro", "atualizado_em"])
        return pix

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
                "amount": int(pix.valor * 100),
            }
        ],
        # A Cora não aceita criação já vencida. O vencimento original segue no
        # nosso banco e o QR recuperado recebe prazo até hoje quando necessário.
        "payment_terms": {"due_date": max(vencimento.data_vencimento, hoje).isoformat()},
    }
    try:
        resposta = cora_api.criar_fatura(payload, pix.idempotency_key)
        _aplicar_resposta(pix, resposta)
    except cora_api.CoraErro as exc:
        pix.status = CobrancaPix.Status.ERRO
        pix.erro = str(exc)
        pix.save(update_fields=["status", "erro", "atualizado_em"])
    return pix


def sincronizar_pix(pix: CobrancaPix) -> CobrancaPix:
    if not pix.cora_id:
        return pix
    resposta = cora_api.consultar_fatura(pix.cora_id)
    _aplicar_resposta(pix, resposta)
    return pix


@transaction.atomic
def _aplicar_resposta(pix: CobrancaPix, resposta: dict) -> None:
    status = STATUS_CORA.get(str(resposta.get("status", "")).upper())
    if not status:
        raise cora_api.CoraErro(f"Status de fatura desconhecido: {resposta.get('status')!r}")
    pix.cora_id = resposta.get("id") or pix.cora_id
    pix.status = status
    pix.total_pago = Decimal(resposta.get("total_paid", 0)) / 100
    pix.pix_copia_e_cola = (resposta.get("pix") or {}).get("emv", pix.pix_copia_e_cola)
    pix.qr_code_url = (
        ((resposta.get("payment_options") or {}).get("bank_slip") or {}).get("url")
        or pix.qr_code_url
    )
    pix.erro = ""
    if status == CobrancaPix.Status.PAGO:
        ocorrencia = resposta.get("occurrence_date")
        if ocorrencia:
            try:
                pix.pago_em = timezone.make_aware(
                    datetime.datetime.fromisoformat(ocorrencia.replace("Z", "+00:00")).replace(tzinfo=None)
                )
            except ValueError:
                pix.pago_em = timezone.now()
        else:
            pix.pago_em = timezone.now()
    pix.save()
    if status == CobrancaPix.Status.PAGO and pix.total_pago > 0:
        _dar_baixa(pix)


def _dar_baixa(pix: CobrancaPix) -> None:
    if Pagamento.objects.filter(vencimento=pix.vencimento).exists():
        return
    Pagamento(
        contrato=pix.vencimento.contrato,
        vencimento=pix.vencimento,
        data_pagamento=(pix.pago_em or timezone.now()).date(),
        valor_pago=pix.total_pago,
        forma=Pagamento.Forma.PIX,
        observacao=f"Baixa automática pela Cora ({pix.cora_id}).",
    ).registrar()


def reconciliar_abertas() -> dict:
    resultado = {"consultadas": 0, "pagas": 0, "erros": 0}
    for pix in CobrancaPix.objects.filter(
        status__in=[CobrancaPix.Status.ABERTO, CobrancaPix.Status.VENCIDO]
    ).exclude(cora_id__isnull=True).exclude(cora_id=""):
        try:
            sincronizar_pix(pix)
            resultado["consultadas"] += 1
            EventoCora.objects.filter(
                recurso_id=pix.cora_id,
                processado=False,
            ).update(processado=True, erro="", processado_em=timezone.now())
            if pix.status == CobrancaPix.Status.PAGO:
                resultado["pagas"] += 1
        except cora_api.CoraErro as exc:
            pix.erro = str(exc)
            pix.save(update_fields=["erro", "atualizado_em"])
            resultado["erros"] += 1
    return resultado
