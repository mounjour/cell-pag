"""Dashboard financeiro: todo o dinheiro do sistema numa tela só.

Não cria conta nova: reaproveita as de ``servicos`` (relatório do período, painel inicial) e a da cobrança
(``parcelas_a_cobrar``, a mesma que gera a mensagem e o Pix), para os números baterem com as outras telas.
"""

import datetime
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.aparelhos.models import Aparelho
from apps.contratos.models import Contrato, ImportacaoContratoPendente
from apps.pagamentos.agenda import parcelas_a_cobrar
from apps.pagamentos.models import CobrancaCora, ComprovanteRecebido, ConfiguracaoCobranca, Pagamento, RecebimentoCora, Vencimento
from apps.pagamentos.proximas import proximas_cobrancas

from .servicos import ZERO, _com_valor_devido, montar_painel_inicial, montar_relatorio

ZERO_DEC = Decimal("0.00")
DIAS_DO_GRAFICO_DIARIO = 62  # acima disso, as entradas são somadas por mês

FAIXAS_DE_ATRASO = (
    ("1 a 7 dias", 1, 7),
    ("8 a 15 dias", 8, 15),
    ("16 a 30 dias", 16, 30),
    ("31 a 60 dias", 31, 60),
    ("Mais de 60 dias", 61, None),
)

PERIODICIDADES = (
    (Contrato.Estrutura.DIARIA, "Diário"),
    (Contrato.Estrutura.SEMANAL, "Semanal"),
    (Contrato.Estrutura.QUINZENAL, "Quinzenal"),
    (Contrato.Estrutura.MENSAL, "Mensal"),
)


def periodo_anterior(inicio: datetime.date, fim: datetime.date) -> tuple[datetime.date, datetime.date]:
    """O período de mesma duração que termina no dia anterior ao ``inicio``."""
    dias = (fim - inicio).days + 1
    return inicio - datetime.timedelta(days=dias), inicio - datetime.timedelta(days=1)


def variacao(atual: Decimal, anterior: Decimal) -> Decimal | None:
    """Variação percentual em relação ao período anterior; ``None`` quando não há base de comparação."""
    if not anterior:
        return None
    return ((atual - anterior) / anterior * 100).quantize(Decimal("0.1"))


def _porcentagem(parte: Decimal, total: Decimal) -> Decimal | None:
    return (parte / total * 100).quantize(Decimal("0.1")) if total else None


def _entradas_do_periodo(inicio: datetime.date, fim: datetime.date) -> dict:
    """O que entrou, por dia (ou por mês, em períodos longos): parcelas e juros separados."""
    pagamentos = Pagamento.objects.filter(data_pagamento__range=(inicio, fim))
    por_mes = (fim - inicio).days + 1 > DIAS_DO_GRAFICO_DIARIO
    if por_mes:
        linhas = (
            pagamentos.annotate(b=TruncMonth("data_pagamento")).values("b")
            .annotate(parcelas=Coalesce(Sum("valor_pago"), ZERO), juros=Coalesce(Sum("juros_pago"), ZERO))
        )
    else:
        linhas = (
            pagamentos.values(b=F("data_pagamento"))
            .annotate(parcelas=Coalesce(Sum("valor_pago"), ZERO), juros=Coalesce(Sum("juros_pago"), ZERO))
        )
    achados = {linha["b"]: linha for linha in linhas}
    rotulos, parcelas, juros = [], [], []
    if por_mes:
        mes = inicio.replace(day=1)
        while mes <= fim:
            linha = achados.get(mes)
            rotulos.append(f"{mes:%m/%Y}")
            parcelas.append(float(linha["parcelas"]) if linha else 0.0)
            juros.append(float(linha["juros"]) if linha else 0.0)
            mes = (mes.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    else:
        dia = inicio
        while dia <= fim:
            linha = achados.get(dia)
            rotulos.append(f"{dia:%d/%m}")
            parcelas.append(float(linha["parcelas"]) if linha else 0.0)
            juros.append(float(linha["juros"]) if linha else 0.0)
            dia += datetime.timedelta(days=1)
    return {"rotulos": rotulos, "parcelas": parcelas, "juros": juros, "por_mes": por_mes, "tem": any(parcelas) or any(juros)}


def _atraso_por_faixa(hoje: datetime.date) -> dict:
    """Parcelas vencidas hoje, agrupadas por faixa de atraso, e os maiores devedores (mesma conta da cobrança)."""
    faixas = [{"rotulo": r, "de": de, "ate": ate, "parcelas": 0, "saldo": ZERO_DEC, "juros": ZERO_DEC} for r, de, ate in FAIXAS_DE_ATRASO]
    devedores = []
    for contrato in Contrato.objects.exclude(status=Contrato.Status.QUITADO).select_related("cliente"):
        atrasadas = [p for p in parcelas_a_cobrar(contrato, hoje) if p.dias_atraso > 0]
        if not atrasadas:
            continue
        for p in atrasadas:
            faixa = next(f for f in faixas if p.dias_atraso >= f["de"] and (f["ate"] is None or p.dias_atraso <= f["ate"]))
            faixa["parcelas"] += 1
            faixa["saldo"] += p.saldo
            faixa["juros"] += p.juros
        devedores.append({
            "contrato": contrato, "dias": max(p.dias_atraso for p in atrasadas), "parcelas": len(atrasadas),
            "saldo": sum((p.saldo for p in atrasadas), ZERO_DEC), "juros": sum((p.juros for p in atrasadas), ZERO_DEC),
        })
    for f in faixas:
        f["total"] = f["saldo"] + f["juros"]
    total = sum((f["total"] for f in faixas), ZERO_DEC)
    maior = max((f["total"] for f in faixas), default=ZERO_DEC)
    for f in faixas:
        f["barra"] = int(f["total"] / maior * 100) if maior else 0
    for d in devedores:
        d["total"] = d["saldo"] + d["juros"]
    devedores.sort(key=lambda d: d["total"], reverse=True)
    return {
        "faixas": faixas, "total": total, "parcelas": sum(f["parcelas"] for f in faixas),
        "saldo": sum((f["saldo"] for f in faixas), ZERO_DEC), "juros": sum((f["juros"] for f in faixas), ZERO_DEC),
        "devedores": devedores[:10], "contratos_em_atraso": len(devedores),
    }


def _agenda(hoje: datetime.date, dias: int = 30, mostrar: int = 12) -> dict:
    """O que vai vencer nos próximos ``dias``: totais de 7 e 30 dias, o que sai por dia e as próximas cobranças."""
    dados = proximas_cobrancas(dias, hoje=hoje)
    limite_7 = hoje + datetime.timedelta(days=7)
    total_7 = sum((g["total"] for g in dados["grupos"] if g["data"] <= limite_7), ZERO_DEC)
    itens = [(g["data"], i["parcela"]) for g in dados["grupos"] for i in g["itens"]]
    return {
        "dias": dias, "total": dados["total"], "quantidade": dados["quantidade"], "total_7": total_7,
        "rotulos": [f"{g['data']:%d/%m}" for g in dados["grupos"]],
        "valores": [float(g["total"]) for g in dados["grupos"]],
        "proximas": [
            {"data": data, "cliente": p.contrato.cliente, "contrato": p.contrato, "estrutura": p.contrato.get_estrutura_display(), "valor": p.saldo}
            for data, p in itens[:mostrar]
        ],
        "mais": max(len(itens) - mostrar, 0),
    }


def _por_periodicidade(inicio: datetime.date, fim: datetime.date) -> list[dict]:
    """Quadro por frequência de pagamento: contratos ativos, previsto e recebido no período, e a participação no recebido."""
    ativos = dict(
        Contrato.objects.exclude(status=Contrato.Status.QUITADO).values("estrutura").annotate(n=Count("pk")).values_list("estrutura", "n")
    )
    previsto = dict(
        _com_valor_devido(Vencimento.objects.filter(data_vencimento__range=(inicio, fim)))
        .values("contrato__estrutura").annotate(t=Coalesce(Sum("valor_devido"), ZERO)).values_list("contrato__estrutura", "t")
    )
    recebido = dict(
        Pagamento.objects.filter(data_pagamento__range=(inicio, fim))
        .values("contrato__estrutura").annotate(t=Coalesce(Sum("valor_pago"), ZERO)).values_list("contrato__estrutura", "t")
    )
    total_recebido = sum(recebido.values(), ZERO_DEC)
    conhecidas = {chave for chave, _ in PERIODICIDADES}
    outras = {k for k in (*ativos, *previsto, *recebido) if k not in conhecidas}  # frequência antiga, sem linha própria
    linhas = [
        {
            "rotulo": rotulo, "contratos": ativos.get(chave, 0), "previsto": previsto.get(chave, ZERO_DEC),
            "recebido": recebido.get(chave, ZERO_DEC),
            "participacao": _porcentagem(recebido.get(chave, ZERO_DEC), total_recebido),
        }
        for chave, rotulo in PERIODICIDADES
    ]
    if outras:
        rec = sum((recebido.get(k, ZERO_DEC) for k in outras), ZERO_DEC)
        linhas.append({
            "rotulo": "Outras", "contratos": sum(ativos.get(k, 0) for k in outras),
            "previsto": sum((previsto.get(k, ZERO_DEC) for k in outras), ZERO_DEC), "recebido": rec,
            "participacao": _porcentagem(rec, total_recebido),
        })
    linhas.append({
        "rotulo": "Total", "contratos": sum(l["contratos"] for l in linhas), "previsto": sum((l["previsto"] for l in linhas), ZERO_DEC),
        "recebido": total_recebido, "participacao": Decimal("100.0") if total_recebido else None, "total": True,
    })
    return linhas


def _carteira(hoje: datetime.date, painel: dict) -> dict:
    """Contratos ativos, receita recorrente por frequência e o que ainda falta receber (gerado e por gerar)."""
    ativos = list(Contrato.objects.exclude(status=Contrato.Status.QUITADO).annotate(n_parcelas_geradas=Count("vencimentos")))
    por_dia = sum((c.valor_parcela or ZERO_DEC for c in ativos if c.estrutura == Contrato.Estrutura.DIARIA), ZERO_DEC)
    por_semana = sum((c.valor_parcela or ZERO_DEC for c in ativos if c.estrutura == Contrato.Estrutura.SEMANAL), ZERO_DEC) + sum(
        (c.valor_parcela or ZERO_DEC for c in ativos if c.estrutura == Contrato.Estrutura.QUINZENAL), ZERO_DEC
    ) / 2
    futuras = sum(
        (max(c.num_parcelas - c.n_parcelas_geradas, 0) * c.valor_parcela for c in ativos if c.num_parcelas and c.valor_parcela), ZERO_DEC
    )
    mes_cheio = _com_valor_devido(
        Vencimento.objects.filter(data_vencimento__year=hoje.year, data_vencimento__month=hoje.month)
    ).aggregate(v=Coalesce(Sum("valor_devido"), ZERO))["v"]
    contagem = painel["status_contagem"]
    n = len(ativos)
    return {
        "ativos": n, "ticket_medio": painel["ticket_medio"],
        "em_dia": contagem.get("em_dia", 0), "atrasados": contagem.get("atrasado", 0), "inadimplentes": contagem.get("inadimplente", 0),
        "quitados": contagem.get("quitado", 0),
        "adimplencia": _porcentagem(Decimal(contagem.get("em_dia", 0)), Decimal(n)),
        "inadimplencia": _porcentagem(Decimal(contagem.get("atrasado", 0) + contagem.get("inadimplente", 0)), Decimal(n)),
        "receita_por_dia": por_dia, "receita_por_semana": por_semana,
        "n_diarios": sum(c.estrutura == Contrato.Estrutura.DIARIA for c in ativos),
        "n_semanais": sum(c.estrutura == Contrato.Estrutura.SEMANAL for c in ativos),
        "n_quinzenais": sum(c.estrutura == Contrato.Estrutura.QUINZENAL for c in ativos),
        "previsto_do_mes": mes_cheio,
        "a_receber_gerado": painel["a_receber"], "a_receber_futuro": futuras, "a_receber_total": painel["a_receber"] + futuras,
        "sem_prazo": sum(1 for c in ativos if not c.num_parcelas),
    }


def _ranking(inicio: datetime.date, fim: datetime.date, limite: int = 10) -> list[dict]:
    linhas = list(
        Pagamento.objects.filter(data_pagamento__range=(inicio, fim))
        .values("contrato__cliente_id", "contrato__cliente__nome")
        .annotate(total=Sum("valor_pago"), n=Count("pk")).order_by("-total")[:limite]
    )
    maior = linhas[0]["total"] if linhas else ZERO_DEC
    return [
        {"cliente_id": l["contrato__cliente_id"], "nome": l["contrato__cliente__nome"], "total": l["total"], "n": l["n"],
         "barra": int(l["total"] / maior * 100) if maior else 0}
        for l in linhas
    ]


def _aparelhos(inicio: datetime.date, fim: datetime.date) -> dict:
    """Dinheiro investido e parado em aparelhos (o custo é de uso interno)."""
    no_periodo = Aparelho.objects.filter(data_compra__range=(inicio, fim)).aggregate(n=Count("pk"), v=Coalesce(Sum("custo"), ZERO))
    parados = Aparelho.objects.filter(contrato__isnull=True).aggregate(n=Count("pk"), v=Coalesce(Sum("custo"), ZERO))
    return {
        "comprados_n": no_periodo["n"], "comprados_valor": no_periodo["v"],
        "estoque_n": parados["n"], "estoque_valor": parados["v"],
    }


def _alertas(d: dict) -> list[dict]:
    """Indicadores que pedem atenção, com a gravidade de cada um (como a aba de alertas da planilha)."""
    from apps.pagamentos import rotinas

    comprovantes = ComprovanteRecebido.objects.filter(status=ComprovanteRecebido.Status.AGUARDANDO).count()
    duplicados = CobrancaCora.objects.filter(duplicada=True, duplicidade_resolvida_em__isnull=True).count()
    pix_erro = CobrancaCora.objects.filter(status=CobrancaCora.Status.ERRO).count()
    pendencias = ImportacaoContratoPendente.objects.filter(resolvida_em__isnull=True).count()
    problemas = rotinas.rotinas_com_problema()
    pausada = ConfiguracaoCobranca.esta_pausada()
    a, c = d["atraso"], d["carteira"]
    itens = [
        ("Contratos em atraso", f"{a['contratos_em_atraso']}", "critico" if a["contratos_em_atraso"] else "ok", "pagamentos:cobrar_hoje"),
        ("Valor em atraso (parcelas e juros)", a["total"], "critico" if a["total"] else "ok", "relatorios:juros"),
        ("Rotinas agendadas com problema", f"{problemas}", "critico" if problemas else "ok", "pagamentos:rotinas"),
        ("Pix pagos em duplicidade", f"{duplicados}", "critico" if duplicados else "ok", "pagamentos:pix_painel"),
        ("Pix com erro", f"{pix_erro}", "atencao" if pix_erro else "ok", "pagamentos:pix_painel"),
        ("Entradas no extrato sem pagamento registrado", f"{d['extrato_sem_baixa_n']}", "atencao" if d["extrato_sem_baixa_n"] else "ok", "pagamentos:recebidos"),
        ("Comprovantes aguardando conferência", f"{comprovantes}", "atencao" if comprovantes else "ok", "pagamentos:pix_painel"),
        ("Pendências de importação abertas", f"{pendencias}", "atencao" if pendencias else "ok", "contratos:importacao_pendencias"),
        ("Contratos sem total de parcelas cadastrado", f"{c['sem_prazo']}", "atencao" if c["sem_prazo"] else "ok", "contratos:lista"),
        ("Cobrança automática", "pausada" if pausada else "ligada", "atencao" if pausada else "ok", "pagamentos:cobrar_hoje"),
    ]
    if d["previsto_ate_hoje"]:
        abaixo = d["taxa_realizada"] is not None and d["taxa_realizada"] < 100
        itens.append(("Recebido sobre o previsto até hoje", f"{d['taxa_realizada']}%".replace(".", ","), "atencao" if abaixo else "ok", None))
    itens.append(("A vencer nos próximos 7 dias", d["agenda"]["total_7"], "info", "pagamentos:proximas_cobrancas"))
    return [{"indicador": i, "valor": v, "dinheiro": isinstance(v, Decimal), "nivel": n, "link": l} for i, v, n, l in itens]


def _dinheiro_e_pix() -> dict:
    sem_baixa = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.NOVO).aggregate(n=Count("pk"), v=Coalesce(Sum("valor"), ZERO))
    aguardando = CobrancaCora.objects.filter(
        status__in=[CobrancaCora.Status.PENDENTE, CobrancaCora.Status.ABERTO]
    ).aggregate(n=Count("pk"), v=Coalesce(Sum("valor"), ZERO))
    return {
        "extrato_sem_baixa_n": sem_baixa["n"], "extrato_sem_baixa_valor": sem_baixa["v"],
        "pix_aguardando_n": aguardando["n"], "pix_aguardando_valor": aguardando["v"],
    }


def _novos_contratos(inicio: datetime.date, fim: datetime.date) -> dict:
    novos = Contrato.objects.filter(data_inicio__range=(inicio, fim)).aggregate(n=Count("pk"), v=Coalesce(Sum("valor_total"), ZERO))
    return {"n": novos["n"], "valor": novos["v"]}


def _evolucao(serie: list[dict]) -> list[dict]:
    """Os últimos meses com o % realizado (recebido ÷ previsto); meses sem movimento ficam de fora."""
    return [{**m, "taxa": _porcentagem(m["recebido"], m["previsto"])} for m in serie if m["recebido"] or m["previsto"]]


def montar_dashboard(inicio: datetime.date, fim: datetime.date, hoje: datetime.date | None = None) -> dict:
    """Tudo o que a tela Financeiro mostra, para o período ``inicio``–``fim`` (a carteira e o atraso são de hoje)."""
    hoje = hoje or timezone.localdate()
    rel = montar_relatorio(inicio, fim)
    ini_ant, fim_ant = periodo_anterior(inicio, fim)
    anterior = montar_relatorio(ini_ant, fim_ant)
    painel = montar_painel_inicial(hoje, meses=12)

    entrou = rel["total_recebido"] + rel["total_juros"]
    entrou_ant = anterior["total_recebido"] + anterior["total_juros"]
    # Previsto "até hoje": só o que já venceu dentro do período (o resto ainda está por vir).
    previsto_ate_hoje = (
        _com_valor_devido(Vencimento.objects.filter(data_vencimento__range=(inicio, min(fim, hoje))))
        .aggregate(v=Coalesce(Sum("valor_devido"), ZERO))["v"]
        if inicio <= hoje else ZERO_DEC
    )
    taxa_realizada = _porcentagem(rel["total_recebido"], previsto_ate_hoje)
    total_formas = sum((l["total"] for l in rel["por_forma"]), ZERO_DEC)
    por_forma = [{**l, "parte": int(l["total"] / total_formas * 100) if total_formas else 0} for l in rel["por_forma"]]
    origem = [
        ("Parcelas que vencem no período", rel["recebido_do_periodo"]),
        ("Parcelas atrasadas de antes", rel["recebido_de_atrasadas"]),
        ("Parcelas adiantadas", rel["recebido_adiantado"]),
        ("Entrada e outros, sem parcela", rel["recebido_sem_parcela"]),
    ]
    maior_origem = max((v for _, v in origem), default=ZERO_DEC)
    atraso = _atraso_por_faixa(hoje)
    d = {
        "inicio": inicio, "fim": fim, "hoje": hoje, "inicio_anterior": ini_ant, "fim_anterior": fim_ant,
        "recebido": rel["total_recebido"], "juros_recebidos": rel["total_juros"], "entrou": entrou,
        "previsto": rel["total_previsto"], "previsto_ate_hoje": previsto_ate_hoje,
        "falta_do_periodo": rel["falta_do_periodo"],
        "taxa_realizada": taxa_realizada,
        "situacao_do_previsto": None if taxa_realizada is None else ("acima" if taxa_realizada > 100 else "dentro" if taxa_realizada == 100 else "abaixo"),
        "n_recebimentos": rel["quantidade_recebimentos"],
        "var_recebido": variacao(rel["total_recebido"], anterior["total_recebido"]),
        "var_entrou": variacao(entrou, entrou_ant), "var_previsto": variacao(rel["total_previsto"], anterior["total_previsto"]),
        "recebido_anterior": anterior["total_recebido"],
        "por_forma": por_forma,
        "origem": [{"rotulo": r, "valor": v, "barra": int(v / maior_origem * 100) if maior_origem else 0} for r, v in origem],
        "por_periodicidade": _por_periodicidade(inicio, fim),
        "ranking": _ranking(inicio, fim),
        "novos_clientes": rel["novos_clientes"], "quitados": rel["contratos_quitados"],
        "novos_contratos": _novos_contratos(inicio, fim),
        "aparelhos": _aparelhos(inicio, fim),
        "entradas": _entradas_do_periodo(inicio, min(fim, hoje)) if inicio <= hoje else {"rotulos": [], "parcelas": [], "juros": [], "por_mes": False, "tem": False},
        "serie_meses": painel["serie_meses"],
        "evolucao": _evolucao(painel["serie_meses"]),
        "atraso": atraso,
        "agenda": _agenda(hoje),
        "carteira": {**_carteira(hoje, painel), "juros_em_aberto": atraso["juros"]},
        **_dinheiro_e_pix(),
    }
    d["potencial_30_dias"] = d["agenda"]["total"] + atraso["total"]
    d["alertas"] = _alertas(d)
    return d
