"""Conferência do sistema com a Cora: o extrato do banco contra o que o sistema registrou.

Só leitura: nada é criado, cancelado nem baixado aqui. Serve para achar, de uma vez, o que estaria errado:

* dinheiro que entrou na Cora e ainda não virou baixa;
* baixas de Pix lançadas no sistema sem o crédito correspondente na Cora (podem estar erradas);
* taxas e mensalidade debitadas (cancelamento de fatura custa R$ 0,30);
* faturas reais abertas na Cora (no Pix estático não deveria haver nenhuma);
* códigos Pix com valor diferente do que a parcela cobra hoje (cliente pagaria o valor errado).
"""

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import cora_api
from .models import CobrancaCora, Pagamento, RecebimentoCora

_CHAVE = "conferencia_cora_{}"
_TTL = 300  # 5 minutos: a leitura do extrato é lenta e não precisa ser a cada clique


def conferir(dias: int = 30, forcar: bool = False) -> dict:
    """Monta o relatório de conferência dos últimos ``dias`` dias. ``erro`` vem preenchido se a Cora não respondeu."""
    chave = _CHAVE.format(dias)
    if not forcar and (guardado := cache.get(chave)) is not None:
        return guardado

    hoje = timezone.localdate()
    inicio = hoje - datetime.timedelta(days=dias)
    relatorio: dict = {"dias": dias, "inicio": inicio, "gerado_em": timezone.now(), "erro": ""}

    movimentos: list[dict] = []
    if settings.CORA_PROVIDER == "cora":
        try:
            movimentos = cora_api.listar_movimentos(inicio, hoje + datetime.timedelta(days=1))
        except cora_api.CoraErro as exc:
            relatorio["erro"] = f"Não consegui consultar o extrato da Cora agora: {exc}"
    else:
        relatorio["erro"] = "A Cora não está conectada neste ambiente (CORA_PROVIDER diferente de cora)."

    relatorio.update(_creditos(movimentos, inicio))
    relatorio.update(_debitos(movimentos))
    relatorio.update(_pix_do_sistema(hoje))
    relatorio["problemas"] = _contar_problemas(relatorio)
    if not relatorio["erro"]:
        cache.set(chave, relatorio, _TTL)
    return relatorio


def _creditos(movimentos: list[dict], inicio: datetime.date) -> dict:
    creditos = [m for m in movimentos if m["sentido"] == "CREDIT" and m["tipo"] == "PIX"]
    registros = {r.entrada_id: r for r in RecebimentoCora.objects.filter(entrada_id__in=[m["id"] for m in creditos])}
    para_conferir = sorted(
        (r for r in registros.values() if r.situacao == RecebimentoCora.Situacao.NOVO), key=lambda r: r.recebido_em,
    )
    return {
        "total_creditos": sum((m["valor"] for m in creditos), Decimal("0.00")),
        "qtd_creditos": len(creditos),
        "sem_registro": [m for m in creditos if m["id"] not in registros],
        "para_conferir": para_conferir,
        "total_para_conferir": sum((r.valor for r in para_conferir), Decimal("0.00")),
        "qtd_vinculados": sum(r.situacao == RecebimentoCora.Situacao.VINCULADO for r in registros.values()),
        "qtd_ignorados": sum(r.situacao == RecebimentoCora.Situacao.IGNORADO for r in registros.values()),
        "baixas_sem_credito": _baixas_sem_credito(inicio),
    }


def _baixas_sem_credito(inicio: datetime.date) -> list[Pagamento]:
    """Pix lançado no sistema que não tem a entrada do extrato ligada nem uma cobrança paga pela Cora."""
    pagas = CobrancaCora.objects.filter(status=CobrancaCora.Status.PAGO).values_list("vencimento_id", flat=True)
    return list(
        Pagamento.objects.filter(forma=Pagamento.Forma.PIX, data_pagamento__gte=inicio, vencimento__isnull=False)
        .exclude(recebimentos_cora__isnull=False)
        .exclude(vencimento_id__in=pagas)
        .select_related("contrato__cliente", "vencimento")
        .order_by("-data_pagamento")
    )


def _debitos(movimentos: list[dict]) -> dict:
    taxas = [m for m in movimentos if m["sentido"] == "DEBIT" and m["tipo"] == "FEE"]
    assinaturas = [m for m in movimentos if m["sentido"] == "DEBIT" and m["tipo"] == "SUBSCRIPTION"]
    return {
        "taxas": sorted(taxas, key=lambda m: m["quando"], reverse=True),
        "total_taxas": sum((m["valor"] for m in taxas), Decimal("0.00")),
        "taxas_de_cancelamento": sum(m["valor"] == Decimal("0.30") for m in taxas),
        "assinaturas": assinaturas,
        "total_assinaturas": sum((m["valor"] for m in assinaturas), Decimal("0.00")),
    }


def _pix_do_sistema(hoje: datetime.date) -> dict:
    from .pix_cora import composicao_do_pix

    abertas = list(
        CobrancaCora.objects.filter(
            status__in=[CobrancaCora.Status.PENDENTE, CobrancaCora.Status.ABERTO, CobrancaCora.Status.VENCIDO]
        ).select_related("vencimento__contrato__cliente")
    )
    desatualizados = []
    for c in abertas:
        try:
            principal, juros = composicao_do_pix(c.vencimento, hoje)
        except Exception:  # um Pix com dado ruim não pode derrubar a conferência
            continue
        esperado = principal + juros
        if esperado > 0 and c.valor != esperado:
            desatualizados.append({"pix": c, "esperado": esperado})
    return {
        "faturas_reais_abertas": [c for c in abertas if c.cora_id],
        "pix_abertos": len(abertas),
        "pix_desatualizados": desatualizados,
        "modo_pix": settings.PIX_MODO,
    }


def _contar_problemas(r: dict) -> int:
    """Quantos grupos de problema pedem atenção (para o selo do topo)."""
    return sum([
        bool(r["sem_registro"]),
        bool(r["para_conferir"]),
        bool(r["baixas_sem_credito"]),
        bool(r["faturas_reais_abertas"]) and r["modo_pix"] == "estatico",
        bool(r["pix_desatualizados"]),
    ])
