"""Promessas de pagamento: quais estão valendo, quais venceram e quais já foram cumpridas.

Só a promessa **mais recente** de cada contrato conta (uma nova combinação substitui a anterior).
Ela é considerada **cumprida** quando entrou algum pagamento do contrato depois de registrada,
ou quando o contrato foi quitado — não depende de ninguém marcar nada.
"""

import datetime
from typing import NamedTuple

from django.db.models import Max
from django.utils import timezone

from apps.contratos.models import Contrato

from .models import ContatoDeCobranca, Pagamento

#: Estados de uma promessa ainda não cumprida.
HOJE, PENDENTE, QUEBRADA = "hoje", "pendente", "quebrada"


class Promessa(NamedTuple):
    contato: ContatoDeCobranca
    estado: str  # "hoje", "pendente" (data futura) ou "quebrada" (data passou sem pagamento)


def promessas_em_aberto(hoje: datetime.date | None = None, contrato_ids=None) -> dict[int, Promessa]:
    """``{contrato_id: Promessa}`` das promessas ainda não cumpridas (a mais recente de cada contrato)."""
    hoje = hoje or timezone.localdate()
    contatos = ContatoDeCobranca.objects.filter(
        resultado=ContatoDeCobranca.Resultado.PROMESSA, promessa_para__isnull=False,
    ).exclude(contrato__status=Contrato.Status.QUITADO).select_related("contrato__cliente")
    if contrato_ids is not None:
        contatos = contatos.filter(contrato_id__in=list(contrato_ids))

    ultimas: dict[int, ContatoDeCobranca] = {}
    for contato in contatos.order_by("-criado_em"):
        ultimas.setdefault(contato.contrato_id, contato)
    if not ultimas:
        return {}

    ultimo_pagamento = dict(
        Pagamento.objects.filter(contrato_id__in=ultimas).values_list("contrato_id").annotate(Max("criado_em"))
    )
    resultado = {}
    for contrato_id, contato in ultimas.items():
        pago_em = ultimo_pagamento.get(contrato_id)
        if pago_em and pago_em >= contato.criado_em:
            continue  # cumprida
        if contato.promessa_para < hoje:
            estado = QUEBRADA
        elif contato.promessa_para == hoje:
            estado = HOJE
        else:
            estado = PENDENTE
        resultado[contrato_id] = Promessa(contato, estado)
    return resultado


def promessas_a_retornar(hoje: datetime.date | None = None) -> list[Promessa]:
    """Promessas para hoje ou já vencidas sem pagamento: é hora de falar com o cliente de novo."""
    itens = [p for p in promessas_em_aberto(hoje).values() if p.estado in (HOJE, QUEBRADA)]
    return sorted(itens, key=lambda p: p.contato.promessa_para)
