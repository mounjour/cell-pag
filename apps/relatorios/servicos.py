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

    Parcela paga (inclusive a maior, cujo troco abateu a seguinte) vale o que foi pago; parcela com baixa
    parcial antiga, cujo saldo foi somado à seguinte (``saldo_repassado``), também vale o que foi pago;
    as demais valem o ``valor_previsto`` (uma baixa parcial nova deixa o saldo na própria parcela).
    """
    return queryset.annotate(
        _tem_baixa=Exists(Pagamento.objects.filter(vencimento=OuterRef("pk"))),
        valor_devido=Case(
            When(_tem_baixa=True, status=Vencimento.Status.PAGO, then=F("valor_pago")),
            When(_tem_baixa=True, saldo_repassado__gt=0, then=F("valor_pago")),
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
        # O que foi pago até o fim do período abate a parcela; o resto continua em aberto. Baixa parcial antiga
        # (``saldo_repassado``): o que faltou já foi somado à seguinte, então a parcela está encerrada.
        pagos_ate_o_fim = [p for p in vencimento.pagamentos.all() if p.data_pagamento <= fim]
        if pagos_ate_o_fim and vencimento.saldo_repassado:
            valor_em_aberto = Decimal("0.00")
        else:
            valor_em_aberto = max(
                vencimento.valor_previsto - sum((p.valor_pago for p in pagos_ate_o_fim), Decimal("0.00")),
                Decimal("0.00"),
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

    # O que falta receber: o saldo de cada parcela em aberto (numa parcial, só o que ainda falta nela).
    a_receber = Vencimento.objects.em_aberto().aggregate(
        v=Coalesce(Sum(F("valor_previsto") - F("valor_pago") - F("saldo_repassado")), ZERO)
    )["v"]

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


# ── Tela inicial (layout "Cobranças de hoje") ────────────────────────────────

JANELA_VENCIMENTOS = 7        # "Próximos vencimentos": de hoje até hoje + 7 dias
GRAFICO_DIAS = 3              # gráfico: 3 dias antes e 3 depois de hoje
LIMITE_LISTA_INICIO = 8


def _escala_do_grafico(maior: Decimal) -> tuple[Decimal, list[Decimal]]:
    """Máximo "redondo" do eixo e as marcas (0, passo, 2*passo…), como no desenho da tela."""
    import math

    v = float(maior)
    if v <= 0:
        return Decimal("100"), [Decimal(x) for x in range(0, 101, 20)]
    p = 10 ** math.floor(math.log10(v))
    n = v / p
    m = 1 if n <= 1 else 2 if n <= 2 else 2.5 if n <= 2.5 else 5 if n <= 5 else 10
    maximo = m * p
    passo = maximo / (4 if m == 2 else 5)
    marcas = []
    t = 0.0
    while t <= maximo + 1e-9:
        marcas.append(Decimal(str(round(t, 2))))
        t += passo
    return Decimal(str(maximo)), marcas


def _rotulo_compacto(v: Decimal) -> str:
    v = float(v)
    if v >= 1000:
        return f"{v / 1000:.1f}".replace(".", ",").removesuffix(",0") + " mil"
    return str(round(v))


def montar_inicio_cobrancas(hoje: datetime.date, painel: dict, hoje_dados: dict) -> dict:
    """Tudo o que a tela inicial mostra além do que já vem de ``montar_painel_inicial`` e ``montar_hoje``."""
    fim_janela = hoje + datetime.timedelta(days=JANELA_VENCIMENTOS)
    base = Vencimento.objects.select_related("contrato__cliente")

    venceu_hoje = list(base.filter(data_vencimento=hoje).exclude(contrato__status=Contrato.Status.QUITADO).order_by("contrato__cliente__nome"))
    for v in venceu_hoje:
        v.paga = v.status == Vencimento.Status.PAGO
        v.valor_exibido = v.valor_pago if v.paga else v.saldo
    proximas_qs = list(base.em_aberto().filter(data_vencimento__gte=hoje, data_vencimento__lte=fim_janela).order_by("data_vencimento", "contrato__cliente__nome"))
    for v in proximas_qs:
        v.valor_exibido = v.saldo
    total_proximos = sum((v.valor_exibido for v in proximas_qs), Decimal("0.00"))

    # Contratos por situação (a barra e as linhas ao lado)
    ids_vencidos = set(base.em_aberto().filter(data_vencimento__lt=hoje).values_list("contrato_id", flat=True))
    n_vencendo = len({v.contrato_id for v in proximas_qs} - ids_vencidos)
    contagem = painel["status_contagem"]
    n_inad, n_atr = painel["inadimplentes"], painel["atrasados_contratos"]
    n_dia = max(0, contagem.get("em_dia", 0) - n_vencendo)
    total_ctr = max(painel["contratos_ativos"], 1)
    situacoes = [
        {"rotulo": "Em dia", "n": n_dia, "cor": "var(--ic-ok)"},
        {"rotulo": f"Parcela nos próximos {JANELA_VENCIMENTOS} dias", "n": n_vencendo, "cor": "var(--ic-warn)"},
        {"rotulo": "Atrasado", "n": n_atr, "cor": "#d97a2b"},
        {"rotulo": "Inadimplente", "n": n_inad, "cor": "var(--ic-danger)"},
    ]
    for s in situacoes:
        s["pct"] = round(s["n"] / total_ctr * 100, 2)

    # Gráfico: recebido até hoje + previsto de hoje em diante
    ini = hoje - datetime.timedelta(days=GRAFICO_DIAS)
    fim = hoje + datetime.timedelta(days=GRAFICO_DIAS)
    recebido_por_dia = dict(
        Pagamento.objects.filter(data_pagamento__range=(ini, hoje)).values("data_pagamento").annotate(t=Coalesce(Sum("valor_pago"), ZERO)).values_list("data_pagamento", "t")
    )
    previsto_por_dia: dict = {}
    for v in base.em_aberto().filter(data_vencimento__range=(hoje, fim)):
        previsto_por_dia[v.data_vencimento] = previsto_por_dia.get(v.data_vencimento, Decimal("0.00")) + v.saldo
    dias = []
    for i in range((fim - ini).days + 1):
        d = ini + datetime.timedelta(days=i)
        rec = recebido_por_dia.get(d, Decimal("0.00")) if d <= hoje else Decimal("0.00")
        prev = previsto_por_dia.get(d, Decimal("0.00")) if d >= hoje else Decimal("0.00")
        dias.append({"data": d, "rec": rec, "prev": prev, "total": rec + prev, "hoje": d == hoje})
    maximo, marcas = _escala_do_grafico(max(d["total"] for d in dias))
    for d in dias:
        d["altura"] = float(d["total"] / maximo * 100)
        d["rec_pct"] = float(d["rec"] / d["total"] * 100) if d["total"] else 0
        d["prev_pct"] = float(d["prev"] / d["total"] * 100) if d["total"] else 0
        d["rotulo"] = _rotulo_compacto(d["total"])
    marcas = [{"valor": m, "pct": float(m / maximo * 100), "rotulo": _rotulo_compacto(m)} for m in marcas]

    ultimos = list(
        Pagamento.objects.filter(data_pagamento__range=(ini, hoje)).select_related("contrato__cliente").order_by("-data_pagamento", "-criado_em")
    )
    for p in ultimos:
        p.hora = timezone.localtime(p.criado_em).strftime("%H:%M")
    total_pix = sum((p.valor_pago for p in ultimos if p.forma == Pagamento.Forma.PIX), Decimal("0.00"))
    total_dinheiro = sum((p.valor_pago for p in ultimos if p.forma == Pagamento.Forma.DINHEIRO), Decimal("0.00"))

    a_cobrar, recebido = hoje_dados["a_cobrar_valor"], hoje_dados["recebido_hoje"]
    progresso = round(recebido / (recebido + a_cobrar) * 100) if (recebido + a_cobrar) > 0 else 100

    fila = hoje_dados["fila"]
    prioridade = fila[0] if fila and fila[0]["situacao"].dias_atraso else None

    return {
        "fim_janela": fim_janela,
        "venceu_hoje": venceu_hoje,
        "proximas": proximas_qs[:LIMITE_LISTA_INICIO],
        "proximas_n": len(proximas_qs),
        "proximas_restante": max(len(proximas_qs) - LIMITE_LISTA_INICIO, 0),
        "total_proximos": total_proximos,
        "vencem_hoje_abertas": sum(1 for v in venceu_hoje if not v.paga),
        "n_clientes_atraso": Vencimento.objects.em_aberto().filter(data_vencimento__lt=hoje).values("contrato__cliente").distinct().count(),
        "progresso": progresso,
        "situacoes": situacoes,
        "grafico": {"dias": dias, "marcas": marcas, "ini": ini, "fim": fim,
                    "recebido": sum((d["rec"] for d in dias), Decimal("0.00")), "previsto": sum((d["prev"] for d in dias), Decimal("0.00"))},
        "ultimos": ultimos[:LIMITE_LISTA_INICIO + 2],
        "ultimos_total": sum((p.valor_pago for p in ultimos), Decimal("0.00")),
        "ultimos_pix": total_pix,
        "ultimos_dinheiro": total_dinheiro,
        "prioridade": prioridade,
    }
