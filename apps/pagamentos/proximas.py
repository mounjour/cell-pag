"""Próximas cobranças: o que a rotina das 8h30 vai cobrar nos próximos dias.

Parcelas em aberto, sem baixa, de contratos não quitados, cuja data de cobrança cai de amanhã em diante.
Parcela vencida ou do dia continua no "Cobrar hoje". Só existem as parcelas já geradas (a rotina gera
com ~60 dias de antecedência), o que cobre as janelas de 7, 14 e 30 dias.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from django.db.models import Count, F, Max

from apps.contratos.models import Contrato

from .contatos import promessas_em_aberto
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
    promessas = promessas_em_aberto(hoje, contrato_ids={p.contrato_id for p in parcelas})
    grupos: list[dict] = []
    for parcela in parcelas:
        if not grupos or grupos[-1]["data"] != parcela.data_vencimento:
            grupos.append({"data": parcela.data_vencimento, "itens": [], "total": Decimal("0.00")})
        grupos[-1]["itens"].append(
            {"parcela": parcela, "suspensa": parcela.pk in suspensas, "promessa": promessas.get(parcela.contrato_id)}
        )
        grupos[-1]["total"] += parcela.saldo
    return {
        "dias": dias, "grupos": grupos, "quantidade": len(parcelas), "sem_parcelas": contratos_sem_parcelas(fim),
        "total": sum((g["total"] for g in grupos), Decimal("0.00")),
    }


def contratos_sem_parcelas(ate: datetime.date) -> list:
    """Contratos ativos cujas parcelas geradas acabam antes de ``ate`` embora ainda faltem parcelas.

    Normalmente a rotina gera as parcelas com ~60 dias de antecedência; se aparece alguém aqui, as
    cobranças dele não estão na lista acima e a geração precisa rodar (botão "Gerar parcelas").
    """
    return list(
        Contrato.objects.exclude(status=Contrato.Status.QUITADO).exclude(valor_parcela__isnull=True)
        .annotate(geradas=Count("vencimentos"), ultima=Max("vencimentos__data_vencimento"))
        .filter(num_parcelas__gt=F("geradas"), ultima__lte=ate)
        .select_related("cliente").order_by("cliente__nome")
    )
