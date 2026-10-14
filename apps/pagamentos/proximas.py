"""Próximas cobranças: o que a rotina das 8h30 vai cobrar nos próximos dias.

Parcelas em aberto, sem baixa, de contratos não quitados, cuja data de cobrança cai de amanhã em diante.
Parcela vencida ou do dia continua no "Cobrar hoje". Só existem as parcelas já geradas (a rotina gera
com ~60 dias de antecedência), o que cobre as janelas de 7, 14 e 30 dias.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from .models import CobrancaCora, Vencimento

JANELAS = (7, 14, 30)


def proximas_cobrancas(dias: int = 14, hoje: datetime.date | None = None) -> dict:
    """``{"dias", "grupos": [{"data", "itens", "total"}], "total", "quantidade"}`` agrupado por data."""
    hoje = hoje or timezone.localdate()
    fim = hoje + datetime.timedelta(days=dias)
    parcelas = list(
        Vencimento.objects.filter(data_vencimento__gt=hoje, data_vencimento__lte=fim)
        .exclude(status=Vencimento.Status.PAGO)
        .exclude(pagamentos__isnull=False)
        .exclude(contrato__status="quitado")
        .select_related("contrato__cliente")
        .order_by("data_vencimento", "contrato__cliente__nome", "numero")
    )
    suspensas = set(
        CobrancaCora.objects.filter(vencimento__in=parcelas, status=CobrancaCora.Status.CANCELADO)
        .values_list("vencimento_id", flat=True)
    )
    grupos: list[dict] = []
    for parcela in parcelas:
        if not grupos or grupos[-1]["data"] != parcela.data_vencimento:
            grupos.append({"data": parcela.data_vencimento, "itens": [], "total": Decimal("0.00")})
        grupos[-1]["itens"].append({"parcela": parcela, "suspensa": parcela.pk in suspensas})
        grupos[-1]["total"] += parcela.saldo
    return {
        "dias": dias, "grupos": grupos, "quantidade": len(parcelas),
        "total": sum((g["total"] for g in grupos), Decimal("0.00")),
    }
