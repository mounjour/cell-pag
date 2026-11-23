"""Exclusão definitiva de contrato e de cliente, com tudo o que depende deles.

As relações de pagamento, cobrança, acordo etc. são ``on_delete=PROTECT`` para ninguém apagar
histórico por engano. Aqui a exclusão é uma decisão explícita da equipe: o que protege é apagado
antes, de dentro para fora, tudo numa transação (ou apaga tudo, ou nada).
"""

import logging

from django.db import transaction
from django.db.models import ProtectedError

logger = logging.getLogger(__name__)


def _apagar(objeto) -> None:
    """Apaga ``objeto``; se algo o protege, apaga primeiro o que protege (recursivo)."""
    while True:
        try:
            objeto.delete()
            return
        except ProtectedError as erro:
            for protetor in list(erro.protected_objects):
                _apagar(protetor)


def _cancelar_pix_abertos(contrato) -> None:
    """Melhor esforço: Pix ainda aberto não pode continuar valendo depois que o contrato some."""
    from apps.pagamentos.models import CobrancaCora
    from apps.pagamentos.pix_cora import cancelar_cobranca

    abertos = CobrancaCora.objects.filter(vencimento__contrato=contrato).exclude(
        status__in=[CobrancaCora.Status.PAGO, CobrancaCora.Status.CANCELADO]
    )
    for pix in abertos:
        try:
            cancelar_cobranca(pix, "Contrato excluído")
        except Exception:  # Cora fora do ar ou Pix recém-pago: a exclusão não deve travar por isso
            logger.warning("Pix %s não pôde ser cancelado ao excluir o contrato %s.", pix.pk, contrato.pk, exc_info=True)


def resumo_do_contrato(contrato) -> dict:
    return {"parcelas": contrato.vencimentos.count(), "pagamentos": contrato.pagamentos.count()}


@transaction.atomic
def excluir_contrato(contrato) -> None:
    """Apaga o contrato, suas parcelas, pagamentos, cobranças e acordos. O aparelho volta ao estoque."""
    _cancelar_pix_abertos(contrato)
    _apagar(contrato)


@transaction.atomic
def excluir_cliente(cliente) -> int:
    """Apaga o cliente e todos os contratos dele. Devolve quantos contratos foram apagados."""
    contratos = list(cliente.contratos.all())
    for contrato in contratos:
        excluir_contrato(contrato)
    _apagar(cliente)
    return len(contratos)
