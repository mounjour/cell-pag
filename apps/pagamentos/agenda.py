"""Agenda do dia — quem cobrar hoje (Fase 2).

Lógica extraída de `CobrarHojeView` para ser reaproveitada também pelo
lembrete diário (`apps.pagamentos.lembrete`) — a tela e a mensagem da Yslane
usam exatamente os mesmos contratos e totais, sem duplicar a regra.

Um contrato entra na agenda quando está atrasado (qualquer estrutura) ou
quando a data de referência (`Contrato.data_referencia_atraso()` — a parcela
em aberto mais antiga, ou o `proximo_vencimento` manual sem vencimentos
gerados) é hoje. Reaproveita `Contrato.situacao_atraso` (Fase 4).
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.contratos.models import Contrato

__all__ = ["montar_agenda_do_dia"]


def montar_agenda_do_dia(hoje: datetime.date | None = None) -> dict:
    """Contratos a cobrar hoje + totais.

    Devolve um dict com ``hoje``, ``linhas`` (uma por contrato, ordenadas por
    dias de atraso decrescente) e os totais ``total_previsto``, ``n_atraso``
    e ``n_bloqueio``. Cada linha tem ``contrato``, ``situacao``
    (`SituacaoAtraso`), ``vence_hoje``, ``parcela`` e ``a_cobrar``.
    """
    if hoje is None:
        hoje = timezone.localdate()

    contratos = (
        Contrato.objects.exclude(status=Contrato.Status.QUITADO)
        .select_related("cliente")
        .order_by("cliente__nome", "apelido")
    )

    linhas = []
    total_previsto = Decimal("0.00")
    n_atraso = n_bloqueio = 0
    for ct in contratos:
        situacao = ct.situacao_atraso(hoje=hoje)
        if situacao is None:
            continue  # sem data de referência — nada a cobrar ainda
        vence_hoje = ct.data_referencia_atraso() == hoje
        if not situacao.dias_atraso and not vence_hoje:
            continue

        parcela = ct.valor_parcela or Decimal("0.00")
        a_cobrar = parcela + situacao.juros
        total_previsto += a_cobrar
        if situacao.dias_atraso:
            n_atraso += 1
        if situacao.alertar_bloqueio:
            n_bloqueio += 1

        linhas.append(
            {
                "contrato": ct,
                "situacao": situacao,
                "vence_hoje": vence_hoje and not situacao.dias_atraso,
                "parcela": ct.valor_parcela,
                "a_cobrar": a_cobrar,
            }
        )

    linhas.sort(key=lambda linha: linha["situacao"].dias_atraso, reverse=True)

    # Expõe no painel o estado da mensagem do dia sem misturar a regra da
    # agenda com o mecanismo de envio.
    if linhas:
        from apps.pagamentos.models import Cobranca

        por_contrato = {
            cobranca.contrato_id: cobranca
            for cobranca in Cobranca.objects.filter(
                contrato_id__in=[linha["contrato"].pk for linha in linhas],
                data_alvo=hoje,
                canal=Cobranca.Canal.WHATSAPP,
            )
        }
        for linha in linhas:
            linha["cobranca"] = por_contrato.get(linha["contrato"].pk)

    return {
        "hoje": hoje,
        "linhas": linhas,
        "total_previsto": total_previsto,
        "n_atraso": n_atraso,
        "n_bloqueio": n_bloqueio,
    }
