"""Geração, conciliação e baixa automática das cobranças Pix da Cora."""

import datetime
import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import cora_api
from .comprovantes import ao_confirmar_pix
from .models import CobrancaCora, EventoCora, Pagamento, Vencimento

logger = logging.getLogger("pagamentos.cora")


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


def parcelas_do_pix(vencimento: Vencimento, hoje) -> list:
    """Parcelas que o Pix desta parcela quita: todas as vencidas em aberto do contrato.

    O Pix fica preso à parcela **mais antiga** em aberto, mas cobra o total das
    parcelas vencidas (o juros fica de fora — é combinado à parte). Quando só há
    ela, é só ela. Se ``vencimento`` não é a mais antiga, cobra só o saldo dele.
    """
    from .agenda import parcelas_a_cobrar

    parcelas = parcelas_a_cobrar(vencimento.contrato, hoje)
    if len(parcelas) > 1 and parcelas[0].numero == vencimento.numero:
        return parcelas
    return []


def valor_do_pix(vencimento: Vencimento, hoje) -> Decimal:
    parcelas = parcelas_do_pix(vencimento, hoje)
    if parcelas:
        return sum((p.saldo for p in parcelas), Decimal("0.00"))
    return max(vencimento.saldo, Decimal("0.00"))


def _substituir_fatura(cobranca: CobrancaCora, valor: Decimal) -> bool:
    """Troca a fatura aberta por outra de ``valor`` diferente (total que mudou).

    Cancela a antiga na Cora e zera o registro para o fluxo normal criar uma nova
    (nova chave de idempotência, sem ``cora_id``). Nunca troca fatura já paga
    (a consulta antes de cancelar pode descobrir o pagamento e dar a baixa).
    Devolve ``False`` — e mantém a fatura antiga — se ela foi paga ou se a Cora
    não confirmou o cancelamento: melhor um QR com valor velho do que dois vivos.
    """
    try:
        sincronizar_cobranca(cobranca)  # pode descobrir que já foi paga
        if cobranca.status == CobrancaCora.Status.PAGO:
            return False
        if cobranca.status != CobrancaCora.Status.CANCELADO:
            cora_api.cancelar_fatura(cobranca.cora_id)
            sincronizar_cobranca(cobranca)
            if cobranca.status != CobrancaCora.Status.CANCELADO:
                raise cora_api.CoraErro(
                    f"A Cora não confirmou o cancelamento (status {cobranca.get_status_display()})."
                )
    except cora_api.CoraErro as exc:
        cobranca.erro = f"Não foi possível atualizar o valor do Pix: {exc}"
        cobranca.save(update_fields=["erro", "atualizado_em"])
        logger.warning("Pix %s não substituído: %s", cobranca.cora_id, exc)
        return False
    cobranca.status = CobrancaCora.Status.PENDENTE
    cobranca.cora_id = None
    cobranca.idempotency_key = uuid.uuid4()
    cobranca.valor = valor
    cobranca.total_pago = Decimal("0.00")
    cobranca.pix_copia_e_cola = ""
    cobranca.qr_code_url = ""
    cobranca.erro = ""
    cobranca.save()
    return True


def obter_ou_criar_cobranca(vencimento: Vencimento, hoje=None) -> CobrancaCora:
    hoje = hoje or timezone.localdate()
    valor = valor_do_pix(vencimento, hoje)
    cobranca, _ = CobrancaCora.objects.get_or_create(
        vencimento=vencimento,
        defaults={
            "valor": valor,
            "data_vencimento": vencimento.data_vencimento,
        },
    )
    # Pix cancelado de propósito (botão "Cancelar Pix"): não recria a fatura — quem
    # cancelou quis parar a cobrança automática dessa parcela.
    if cobranca.status == CobrancaCora.Status.CANCELADO:
        return cobranca
    if cobranca.status == CobrancaCora.Status.PAGO:
        return cobranca
    if cobranca.valor != valor:
        # O total a cobrar mudou (entrou outra parcela vencida, ou saiu uma).
        if cobranca.cora_id:
            if settings.CORA_PROVIDER != "cora" or not _substituir_fatura(cobranca, valor):
                return cobranca
        else:
            cobranca.valor = valor
            cobranca.save(update_fields=["valor", "atualizado_em"])
    if cobranca.cora_id or settings.CORA_PROVIDER == "log":
        return cobranca
    if settings.CORA_PROVIDER != "cora":
        cobranca.status = CobrancaCora.Status.ERRO
        cobranca.erro = f"CORA_PROVIDER desconhecido: {settings.CORA_PROVIDER!r}"
        cobranca.save(update_fields=["status", "erro", "atualizado_em"])
        return cobranca

    contrato = vencimento.contrato
    numeros = [p.numero for p in parcelas_do_pix(vencimento, hoje)] or [vencimento.numero]
    rotulo = (
        f"Parcela {numeros[0]}"
        if len(numeros) == 1
        else "Parcelas " + ", ".join(str(n) for n in numeros)
    )
    payload = {
        # Sufixo da chave: uma fatura substituída (total mudou) não repete o código.
        "code": f"vencimento-{vencimento.pk}-{str(cobranca.idempotency_key)[:8]}",
        "customer": {
            "name": contrato.cliente.nome[:60],
            "document": {"identity": contrato.cliente.cpf, "type": "CPF"},
        },
        "services": [
            {
                "name": rotulo[:60],
                "description": f"{contrato.apelido} - {rotulo.lower()}"[:100],
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


def sincronizar_cobranca(cobranca: CobrancaCora, *, tentativas: int | None = None) -> CobrancaCora:
    if not cobranca.cora_id:
        return cobranca
    extra = {} if tentativas is None else {"tentativas": tentativas}
    resposta = cora_api.consultar_fatura(cobranca.cora_id, **extra)
    _aplicar_resposta(cobranca, resposta)
    return cobranca


class CancelamentoRecusado(Exception):
    """A fatura não pode ser cancelada (ex.: já foi paga)."""


def cancelar_cobranca(cobranca: CobrancaCora) -> CobrancaCora:
    """Cancela o Pix de uma parcela — na Cora e no nosso banco.

    Serve para quando o cliente vai pagar por outro meio, a parcela é renegociada
    ou a cobrança foi criada por engano: sem isso o QR continuaria valendo e o
    cliente poderia pagar duas vezes.

    Nunca cancela fatura já paga (levanta `CancelamentoRecusado`). Antes de
    cancelar, consulta a Cora, porque o pagamento pode ter acontecido há pouco e
    ainda não estar refletido aqui. Depois de cancelada, o QR e o copia-e-cola
    guardados são apagados — o código deixou de valer, e a rotina de cobrança não
    pode reenviá-lo ao cliente. Falha de comunicação com a Cora propaga como
    `cora_api.CoraErro` e deixa o registro como estava.
    """
    if cobranca.status == CobrancaCora.Status.CANCELADO:
        return cobranca
    if cobranca.status == CobrancaCora.Status.PAGO:
        raise CancelamentoRecusado("Este Pix já foi pago e não pode ser cancelado.")

    if cobranca.cora_id and settings.CORA_PROVIDER == "cora":
        sincronizar_cobranca(cobranca)  # pode descobrir que já foi paga (e dar a baixa)
        if cobranca.status == CobrancaCora.Status.PAGO:
            raise CancelamentoRecusado("Este Pix acabou de ser pago e não pode ser cancelado.")
        if cobranca.status != CobrancaCora.Status.CANCELADO:
            cora_api.cancelar_fatura(cobranca.cora_id)
            sincronizar_cobranca(cobranca)
            if cobranca.status != CobrancaCora.Status.CANCELADO:
                raise cora_api.CoraErro(
                    f"A Cora não confirmou o cancelamento (status {cobranca.get_status_display()})."
                )
    cobranca.status = CobrancaCora.Status.CANCELADO
    cobranca.pix_copia_e_cola = ""
    cobranca.qr_code_url = ""
    cobranca.erro = ""
    cobranca.save(update_fields=["status", "pix_copia_e_cola", "qr_code_url", "erro", "atualizado_em"])
    return cobranca


def suspender_cobranca(vencimento: Vencimento) -> CobrancaCora:
    """Suspende a cobrança automática de uma parcela — mesmo antes de o Pix existir.

    Se já há Pix, cancela a fatura na Cora (`cancelar_cobranca`); se ainda não há,
    registra um Pix já cancelado, que a rotina diária respeita (não cria fatura
    nem manda mensagem para essa parcela). Nunca mexe em parcela paga.
    """
    if vencimento.status == Vencimento.Status.PAGO:
        raise CancelamentoRecusado("Esta parcela já está paga.")
    cobranca, _ = CobrancaCora.objects.get_or_create(
        vencimento=vencimento,
        defaults={
            "valor": max(vencimento.saldo, Decimal("0.00")),
            "data_vencimento": vencimento.data_vencimento,
        },
    )
    return cancelar_cobranca(cobranca)


def retomar_cobranca(cobranca: CobrancaCora) -> CobrancaCora:
    """Volta a cobrar uma parcela suspensa: a próxima rotina gera uma fatura nova.

    A fatura antiga fica cancelada na Cora; aqui o registro é zerado (nova chave de
    idempotência, sem `cora_id`) para o fluxo normal criar outra do zero.
    """
    if cobranca.status != CobrancaCora.Status.CANCELADO:
        return cobranca
    vencimento = cobranca.vencimento
    if vencimento.status == Vencimento.Status.PAGO:
        raise CancelamentoRecusado("Esta parcela já está paga.")
    cobranca.status = CobrancaCora.Status.PENDENTE
    cobranca.cora_id = None
    cobranca.idempotency_key = uuid.uuid4()
    cobranca.valor = max(vencimento.saldo, Decimal("0.00"))
    cobranca.data_vencimento = vencimento.data_vencimento
    cobranca.total_pago = Decimal("0.00")
    cobranca.pix_copia_e_cola = ""
    cobranca.qr_code_url = ""
    cobranca.erro = ""
    cobranca.save()
    return cobranca


@transaction.atomic
def _aplicar_resposta(cobranca: CobrancaCora, resposta: dict) -> None:
    from apps.contratos.models import Contrato

    # Mesma trava usada pelas baixas manuais: conferir e distribuir são uma
    # única operação, mesmo quando o webhook chega durante uma baixa em dinheiro.
    Contrato.objects.select_for_update().get(pk=cobranca.vencimento.contrato_id)
    cobranca.refresh_from_db()
    status = STATUS_CORA.get(str(resposta.get("status", "")).upper())
    if not status:
        raise cora_api.CoraErro(f"Status de fatura desconhecido: {resposta.get('status')!r}")
    pix = resposta.get("pix") or {}
    bank_slip = (resposta.get("payment_options") or {}).get("bank_slip") or {}

    cobranca.cora_id = resposta.get("id") or cobranca.cora_id
    cobranca.status = status
    cobranca.total_pago = Decimal(resposta.get("total_paid", 0)) / 100
    cobranca.pix_copia_e_cola = pix.get("emv", cobranca.pix_copia_e_cola)
    # A Cora devolve a URL do PNG do QR code em payment_options.bank_slip.url,
    # não dentro do objeto "pix" (que só tem o campo "emv").
    cobranca.qr_code_url = bank_slip.get("url") or cobranca.qr_code_url
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
    # Grava só o que a resposta da Cora altera. Um save() completo apagaria, com o
    # valor antigo deste objeto, campos que outros trechos preenchem por conta
    # própria (confirmacao_enviada_em, duplicada, duplicidade_resolvida_em).
    cobranca.save(
        update_fields=[
            "cora_id", "status", "total_pago", "pix_copia_e_cola", "qr_code_url",
            "erro", "pago_em", "atualizado_em",
        ]
    )
    if status == CobrancaCora.Status.PAGO and cobranca.total_pago > 0:
        _dar_baixa(cobranca)


PREFIXO_BAIXA_AUTOMATICA = "Baixa automática pela Cora"


def _dar_baixa(cobranca: CobrancaCora) -> None:
    if cobranca.duplicada:
        return  # revisão manual permanece pendente mesmo em notificações repetidas
    existente = Pagamento.objects.filter(vencimento=cobranca.vencimento).first()
    if existente is not None:
        # A parcela já tem baixa. Se foi este mesmo Pix (repetição do aviso da
        # Cora), nada a fazer. Se foi outro meio (ex.: dinheiro), o cliente pagou
        # duas vezes: o valor entrou na Cora sem constar no sistema, então marca
        # a duplicidade para o painel Pix mostrar e o financeiro devolver.
        if not existente.observacao.startswith(PREFIXO_BAIXA_AUTOMATICA) and not cobranca.duplicada:
            cobranca.duplicada = True
            cobranca.save(update_fields=["duplicada", "atualizado_em"])
            logger.warning(
                "Pix %s pago em duplicidade: a parcela %s já tinha baixa por outro meio.",
                cobranca.cora_id,
                cobranca.vencimento_id,
            )
        return
    vencimento = cobranca.vencimento
    vencimento.refresh_from_db()
    if (
        vencimento.status == Vencimento.Status.PAGO
        or (
            max(cobranca.valor, cobranca.total_pago) > vencimento.saldo
            and cobranca.total_pago != valor_do_pix(vencimento, timezone.localdate())
        )
    ):
        cobranca.duplicada = True
        cobranca.save(update_fields=["duplicada", "atualizado_em"])
        logger.warning(
            "Pix %s exige revisão manual: valor recebido diverge do saldo atual.",
            cobranca.cora_id,
        )
        return
    pagamento = Pagamento(
        contrato=cobranca.vencimento.contrato,
        vencimento=cobranca.vencimento,
        data_pagamento=(cobranca.pago_em or timezone.now()).date(),
        valor_pago=cobranca.total_pago,
        forma=Pagamento.Forma.PIX,
        observacao=f"{PREFIXO_BAIXA_AUTOMATICA} ({cobranca.cora_id}).",
    )
    pagamento.registrar()
    # Resolve os avisos de comprovante da parcela e confirma ao cliente por WhatsApp.
    ao_confirmar_pix(cobranca, pagamento)


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
