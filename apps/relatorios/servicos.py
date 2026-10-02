import datetime
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, Exists, F, OuterRef, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import Pagamento, Vencimento
from apps.pagamentos.agenda import parcelas_a_cobrar, resumo_cobranca
from apps.pagamentos.atraso import dias_de_atraso

MESES_PT = [
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]


ZERO = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))


def _com_valor_devido(queryset):
    """Anota ``valor_devido``: o que a parcela de fato representa no total.

    Uma baixa parcial (ou a maior) **transporta** a diferença para o
    ``valor_previsto`` da próxima parcela, mas deixa o ``valor_previsto`` da
    parcela paga como estava. Somar os dois contaria o saldo duas vezes (ou
    esqueceria o troco). Por isso, parcela que já recebeu baixa vale o que foi
    pago; sem baixa, vale o ``valor_previsto``.
    """
    return queryset.annotate(
        _tem_baixa=Exists(Pagamento.objects.filter(vencimento=OuterRef("pk"))),
        valor_devido=Case(
            When(_tem_baixa=True, then=F("valor_pago")),
            default=F("valor_previsto"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )


def montar_relatorio(inicio, fim):
    vencimentos = _com_valor_devido(
        Vencimento.objects.filter(data_vencimento__range=(inicio, fim))
    )
    pagamentos = Pagamento.objects.filter(data_pagamento__range=(inicio, fim))

    total_previsto = vencimentos.aggregate(v=Coalesce(Sum("valor_devido"), ZERO))["v"]
    total_recebido = pagamentos.aggregate(v=Coalesce(Sum("valor_pago"), ZERO))["v"]
    total_juros = pagamentos.aggregate(v=Coalesce(Sum("juros_pago"), ZERO))["v"]

    # De onde veio o recebido: parcela que vencia no período, parcela de antes
    # (atrasada) ou de depois (adiantada). Sem isso, comparar recebido com
    # previsto engana: o recebido inclui dinheiro de outras datas.
    def _recebido(**filtro):
        return pagamentos.filter(**filtro).aggregate(v=Coalesce(Sum("valor_pago"), ZERO))["v"]

    recebido_do_periodo = _recebido(vencimento__data_vencimento__range=(inicio, fim))
    recebido_de_atrasadas = _recebido(vencimento__data_vencimento__lt=inicio)
    recebido_adiantado = _recebido(vencimento__data_vencimento__gt=fim)
    recebido_sem_parcela = (
        total_recebido - recebido_do_periodo - recebido_de_atrasadas - recebido_adiantado
    )

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
        # Parcela com baixa até o fim do período está encerrada: a sobra (ou o
        # troco) já foi transportada para a próxima parcela — contar o resto
        # aqui de novo duplicaria o atraso.
        baixada_ate_o_fim = any(
            pagamento.data_pagamento <= fim for pagamento in vencimento.pagamentos.all()
        )
        valor_em_aberto = (
            Decimal("0.00") if baixada_ate_o_fim else vencimento.valor_previsto
        )
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
        "total_juros": total_juros,
        "recebido_do_periodo": recebido_do_periodo,
        "recebido_de_atrasadas": recebido_de_atrasadas,
        "recebido_adiantado": recebido_adiantado,
        "recebido_sem_parcela": recebido_sem_parcela,
        "falta_do_periodo": max(total_previsto - recebido_do_periodo, Decimal("0.00")),
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


def _primeiro_do_mes(data: datetime.date) -> datetime.date:
    return data.replace(day=1)


def _somar_meses(primeiro_do_mes: datetime.date, n: int) -> datetime.date:
    """Avança/retrocede ``n`` meses a partir de um dia 1."""
    total = primeiro_do_mes.month - 1 + n
    ano = primeiro_do_mes.year + total // 12
    mes = total % 12 + 1
    return datetime.date(ano, mes, 1)


def montar_painel_inicial(hoje: datetime.date | None = None, meses: int = 6) -> dict:
    """Resumo para a tela inicial: números-chave de hoje/mês, série mensal
    (recebido × previsto) dos últimos ``meses`` meses, distribuição de status
    dos contratos e os contratos mais atrasados.

    Reaproveita ``montar_relatorio`` para o recorte do mês corrente.
    """
    if hoje is None:
        hoje = timezone.localdate()
    inicio_mes = _primeiro_do_mes(hoje)
    rel_mes = montar_relatorio(inicio_mes, hoje)

    ativos = list(
        Contrato.objects.exclude(status=Contrato.Status.QUITADO).select_related("cliente")
    )
    contagem = {"em_dia": 0, "atrasado": 0, "inadimplente": 0, "quitado": 0}
    atencao = []
    for contrato in ativos:
        situacao = contrato.situacao_atraso(hoje=hoje)
        status = situacao.status if situacao else contrato.status
        contagem[status] = contagem.get(status, 0) + 1
        if situacao and situacao.dias_atraso:
            # Mesma conta da cobrança e da mensagem: todas as parcelas vencidas,
            # cada uma com o próprio juros (não só a mais antiga).
            parcelas = parcelas_a_cobrar(contrato, hoje)
            if parcelas:
                em_aberto = sum((p.total for p in parcelas), Decimal("0.00"))
            else:
                parcela = contrato.parcela_em_aberto()
                saldo = parcela.saldo if parcela else Decimal("0.00")
                em_aberto = saldo + situacao.juros
            atencao.append(
                {
                    "contrato": contrato,
                    "dias_atraso": situacao.dias_atraso,
                    "n_parcelas": len(parcelas),
                    "em_aberto": em_aberto,
                }
            )
    contagem["quitado"] = Contrato.objects.filter(
        status=Contrato.Status.QUITADO
    ).count()
    atencao.sort(key=lambda item: item["dias_atraso"], reverse=True)

    # Só parcelas sem baixa: numa parcial, o que faltou já está no previsto da
    # próxima parcela (contar as duas dobraria o saldo).
    a_receber = (
        Vencimento.objects.exclude(status=Vencimento.Status.PAGO)
        .exclude(pagamentos__isnull=False)
        .aggregate(v=Coalesce(Sum("valor_previsto"), ZERO))["v"]
    )

    n_ativos = len(ativos)
    valor_ativos = sum((c.valor_total for c in ativos), Decimal("0.00"))
    ticket_medio = valor_ativos / n_ativos if n_ativos else Decimal("0.00")

    primeiro = _somar_meses(inicio_mes, -(meses - 1))
    limite = _somar_meses(inicio_mes, 1)
    recebido_mes = dict(
        Pagamento.objects.filter(data_pagamento__gte=primeiro)
        .annotate(m=TruncMonth("data_pagamento"))
        .values("m")
        .annotate(t=Coalesce(Sum("valor_pago"), ZERO))
        .values_list("m", "t")
    )
    previsto_mes = dict(
        _com_valor_devido(
            Vencimento.objects.filter(
                data_vencimento__gte=primeiro, data_vencimento__lt=limite
            )
        )
        .annotate(m=TruncMonth("data_vencimento"))
        .values("m")
        .annotate(t=Coalesce(Sum("valor_devido"), ZERO))
        .values_list("m", "t")
    )
    serie = []
    for i in range(meses):
        mes = _somar_meses(primeiro, i)
        serie.append(
            {
                "rotulo": f"{MESES_PT[mes.month - 1]}/{mes:%y}",
                "recebido": recebido_mes.get(mes, Decimal("0.00")),
                "previsto": previsto_mes.get(mes, Decimal("0.00")),
            }
        )

    return {
        "hoje": hoje,
        "recebido_mes": rel_mes["total_recebido"],
        "previsto_mes": rel_mes["total_previsto"],
        "total_atrasado": rel_mes["total_atrasado"],
        "qtd_atrasados": rel_mes["quantidade_atrasados"],
        "novos_clientes_mes": rel_mes["novos_clientes"],
        "quitados_mes": rel_mes["contratos_quitados"],
        "a_receber": a_receber,
        "contratos_ativos": n_ativos,
        "inadimplentes": contagem.get("inadimplente", 0),
        "atrasados_contratos": contagem.get("atrasado", 0),
        "ticket_medio": ticket_medio,
        "status_contagem": contagem,
        "serie_meses": serie,
        "atencao": atencao[:5],
    }


def montar_juros_em_aberto(hoje: datetime.date | None = None) -> dict:
    """Juros acumulados hoje em cada contrato atrasado (página `/relatorios/juros/`).

    Reaproveita ``resumo_cobranca`` — mesma conta usada na cobrança e nas
    mensagens, então o valor aqui bate com o que o cliente vê no WhatsApp.
    """
    if hoje is None:
        hoje = timezone.localdate()
    ativos = Contrato.objects.exclude(status=Contrato.Status.QUITADO).select_related("cliente")
    linhas = []
    total = Decimal("0.00")
    for contrato in ativos:
        situacao = contrato.situacao_atraso(hoje=hoje)
        if not situacao or not situacao.dias_atraso:
            continue
        resumo = resumo_cobranca(contrato, hoje)
        if not resumo["juros"]:
            continue
        linhas.append(
            {
                "contrato": contrato,
                "dias_atraso": situacao.dias_atraso,
                "quantidade_parcelas": resumo["quantidade"],
                "juros": resumo["juros"],
            }
        )
        total += resumo["juros"]
    linhas.sort(key=lambda item: item["juros"], reverse=True)
    return {"hoje": hoje, "linhas": linhas, "total": total}


FILA_DE_ACAO_TAMANHO = 4


def montar_hoje(hoje: datetime.date | None = None, limite_fila: int = FILA_DE_ACAO_TAMANHO) -> dict:
    """O que pede ação agora, para a tela inicial.

    ``a_cobrar_n``/``a_cobrar_valor`` vêm da mesma agenda do "Cobrar hoje"; a
    ``fila`` são as primeiras linhas dela (já ordenadas pelo maior atraso).
    ``recebido_hoje`` soma as baixas com data de hoje.
    """
    from apps.pagamentos.agenda import montar_agenda_do_dia

    if hoje is None:
        hoje = timezone.localdate()
    agenda = montar_agenda_do_dia(hoje=hoje)
    recebido = Pagamento.objects.filter(data_pagamento=hoje).aggregate(
        total=Coalesce(Sum("valor_pago"), ZERO), n=Count("pk")
    )
    return {
        "a_cobrar_n": len(agenda["linhas"]),
        "a_cobrar_valor": agenda["total_previsto"],
        "n_atraso": agenda["n_atraso"],
        "n_bloqueio": agenda["n_bloqueio"],
        "recebido_hoje": recebido["total"],
        "recebido_hoje_n": recebido["n"],
        "fila": agenda["linhas"][:limite_fila],
        "fila_restante": max(len(agenda["linhas"]) - limite_fila, 0),
    }
