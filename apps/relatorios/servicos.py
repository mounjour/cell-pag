from decimal import Decimal

from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import Pagamento, Vencimento
from apps.pagamentos.atraso import dias_de_atraso


ZERO = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))


def montar_relatorio(inicio, fim):
    vencimentos = Vencimento.objects.filter(data_vencimento__range=(inicio, fim))
    pagamentos = Pagamento.objects.filter(data_pagamento__range=(inicio, fim))

    total_previsto = vencimentos.aggregate(v=Coalesce(Sum("valor_previsto"), ZERO))["v"]
    total_recebido = pagamentos.aggregate(v=Coalesce(Sum("valor_pago"), ZERO))["v"]

    # Calcula o retrato no fim do período, respeitando a janela especial da
    # semanal. Uma parcela paga depois desse dia ainda aparece como atrasada no
    # relatório histórico; uma paga até esse dia não aparece.
    candidatos = (
        Vencimento.objects.filter(data_vencimento__lt=fim)
        .select_related("contrato__cliente")
        .prefetch_related("pagamentos")
        .order_by("data_vencimento", "contrato__cliente__nome")
    )
    atrasados = []
    total_atrasado = Decimal("0.00")
    for vencimento in candidatos:
        dias = dias_de_atraso(
            vencimento.data_vencimento,
            fim,
            vencimento.contrato.estrutura,
        )
        pago_ate_o_fim = sum(
            (
                pagamento.valor_pago
                for pagamento in vencimento.pagamentos.all()
                if pagamento.data_pagamento <= fim
            ),
            Decimal("0.00"),
        )
        valor_em_aberto = max(vencimento.valor_previsto - pago_ate_o_fim, Decimal("0.00"))
        if dias > 0 and valor_em_aberto > 0:
            vencimento.valor_em_aberto = valor_em_aberto
            vencimento.dias_atraso_relatorio = dias
            atrasados.append(vencimento)
            total_atrasado += valor_em_aberto

    recebimentos = pagamentos.select_related(
        "contrato__cliente", "vencimento", "usuario_baixa"
    ).order_by("-data_pagamento", "contrato__cliente__nome")

    por_forma = list(
        pagamentos.values("forma")
        .annotate(total=Coalesce(Sum("valor_pago"), ZERO), quantidade=Count("id"))
        .order_by("forma")
    )
    formas = dict(Pagamento.Forma.choices)
    for linha in por_forma:
        linha["forma_label"] = formas.get(linha["forma"], linha["forma"])

    return {
        "inicio": inicio,
        "fim": fim,
        "total_previsto": total_previsto,
        "total_recebido": total_recebido,
        "diferenca": total_recebido - total_previsto,
        "total_atrasado": total_atrasado,
        "quantidade_atrasados": len(atrasados),
        "quantidade_recebimentos": pagamentos.count(),
        "novos_clientes": Cliente.objects.filter(criado_em__date__range=(inicio, fim)).count(),
        "contratos_quitados": Contrato.objects.filter(quitado_em__range=(inicio, fim)).count(),
        "atrasados": atrasados,
        "recebimentos": list(recebimentos),
        "por_forma": por_forma,
    }
