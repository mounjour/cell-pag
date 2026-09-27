"""Encerra a cobrança automática de uma parcela paga por outro meio.

Quando o financeiro registra à mão um pagamento (dinheiro, transferência...) de
uma parcela que o sistema já estava cobrando, sobram dois "restos" que podem
confundir ou custar dinheiro:

- o **Pix** gerado na Cora, que continua valendo até o vencimento (o cliente
  poderia pagar de novo);
- a **mensagem de WhatsApp** já enviada, pedindo um pagamento que já foi feito.

``encerrar_cobranca_automatica`` cuida dos dois e devolve avisos para mostrar a
quem registrou a baixa. Nunca impede nem desfaz o pagamento: qualquer falha
vira um aviso com o passo manual que falta.
"""

import datetime
import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from . import cora_api
from .models import Cobranca, CobrancaCora
from .pix_cora import CancelamentoRecusado, cancelar_cobranca
from .whatsapp import WhatsAppErro, apagar_mensagem

logger = logging.getLogger("pagamentos.limpeza")

# Aviso mostrado na tela: (nível, texto). Níveis: "success", "info", "warning".
Aviso = tuple[str, str]

_PIX_ABERTOS = (
    CobrancaCora.Status.PENDENTE,
    CobrancaCora.Status.ABERTO,
    CobrancaCora.Status.VENCIDO,
    CobrancaCora.Status.ERRO,
)
_MENSAGEM_ENVIADA = (
    Cobranca.Status.ENVIADO,
    Cobranca.Status.ENTREGUE,
    Cobranca.Status.LIDO,
)


def encerrar_cobranca_automatica(pagamento) -> list[Aviso]:
    """Cancela o Pix e resolve as mensagens da parcela do ``pagamento``."""
    vencimento = pagamento.vencimento
    if vencimento is None:
        return []
    avisos: list[Aviso] = []
    avisos += _cancelar_pix(vencimento)
    avisos += _resolver_mensagens(pagamento, vencimento)
    return avisos


def _cancelar_pix(vencimento) -> list[Aviso]:
    pix = CobrancaCora.objects.filter(vencimento=vencimento).first()
    if pix is None or pix.status not in _PIX_ABERTOS:
        return []
    numero = vencimento.numero
    try:
        cancelar_cobranca(pix)
    except CancelamentoRecusado:
        # A Cora informou que o cliente JÁ pagou o Pix: ele pagou duas vezes.
        pix.refresh_from_db()
        return [(
            "warning",
            f"Atenção: o cliente também pagou o Pix da parcela {numero}. O valor entrou na Cora "
            "e precisa ser devolvido — veja o alerta no painel Pix.",
        )]
    except cora_api.CoraErro as exc:
        logger.warning("Não consegui cancelar o Pix %s: %s", pix.pk, exc)
        return [(
            "warning",
            f"O pagamento foi registrado, mas não consegui cancelar o Pix da parcela {numero} na "
            "Cora. Cancele-o no painel Pix, senão o cliente ainda pode pagá-lo.",
        )]
    return [("info", f"Pix da parcela {numero} cancelado: o QR code não vale mais.")]


def _resolver_mensagens(pagamento, vencimento) -> list[Aviso]:
    """Mensagens ainda não enviadas são canceladas; as já enviadas (dentro da
    janela do WhatsApp) são apagadas do celular do cliente, se possível."""
    candidatas = Cobranca.objects.filter(contrato=pagamento.contrato).filter(
        Q(vencimento=vencimento) | Q(vencimento__isnull=True)
    )
    cancelar = candidatas.filter(status__in=(Cobranca.Status.PENDENTE, Cobranca.Status.ERRO))
    cancelar.update(status=Cobranca.Status.CANCELADO, atualizado_em=timezone.now())

    janela = datetime.timedelta(hours=settings.WHATSAPP_APAGAR_JANELA_HORAS)
    limite = timezone.now() - janela
    enviadas = list(
        candidatas.filter(status__in=_MENSAGEM_ENVIADA, enviado_em__gte=limite)
    )
    if not enviadas:
        return []

    if not settings.WHATSAPP_APAGAR_AO_BAIXAR:
        return [_aviso_avisar_cliente(pagamento, "não foi apagada (a função está desligada)")]

    apagadas, falhas = 0, []
    for cobranca in enviadas:
        try:
            for identificador in filter(None, (cobranca.id_externo, cobranca.id_externo_codigo)):
                apagar_mensagem(destinatario=cobranca.destinatario, id_mensagem=identificador)
        except WhatsAppErro as exc:
            logger.warning("Não consegui apagar a cobrança %s: %s", cobranca.pk, exc)
            falhas.append(cobranca)
            continue
        cobranca.status = Cobranca.Status.APAGADO
        cobranca.save(update_fields=["status", "atualizado_em"])
        apagadas += 1

    avisos: list[Aviso] = []
    if apagadas:
        avisos.append((
            "info",
            "A mensagem de cobrança foi apagada do WhatsApp do cliente."
            if apagadas == 1
            else f"{apagadas} mensagens de cobrança foram apagadas do WhatsApp do cliente.",
        ))
    if falhas:
        avisos.append(_aviso_avisar_cliente(pagamento, "não pôde ser apagada"))
    return avisos


def _aviso_avisar_cliente(pagamento, motivo: str) -> Aviso:
    cliente = pagamento.contrato.cliente
    return (
        "warning",
        f"A mensagem de cobrança já enviada a {cliente.nome} {motivo}. Avise o cliente pelo "
        "WhatsApp que o pagamento foi recebido e a cobrança pode ser ignorada.",
    )
