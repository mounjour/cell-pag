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
from typing import NamedTuple

from django.utils import timezone

from apps.contratos.models import Contrato

__all__ = ["montar_agenda_do_dia", "parcelas_a_cobrar", "ParcelaACobrar"]


class ParcelaACobrar(NamedTuple):
    """Uma parcela em aberto que já pode ser cobrada, com o atraso dela."""

    numero: int
    data_vencimento: datetime.date
    dias_atraso: int
    saldo: Decimal
    juros: Decimal

    @property
    def total(self) -> Decimal:
        return self.saldo + self.juros


def parcelas_a_cobrar(contrato, hoje: datetime.date) -> list[ParcelaACobrar]:
    """Cada parcela em aberto vencida (ou que vence hoje), do nº mais antigo ao mais novo.

    O atraso e o juros são **de cada parcela** (contados a partir do próprio
    vencimento), não do contrato. Parcela que já recebeu baixa fica de fora —
    o que faltou nela já foi transportado para a seguinte (ver
    ``Pagamento.registrar``). Vazia quando o contrato ainda não tem vencimentos
    gerados.
    """
    from apps.pagamentos import atraso
    from apps.pagamentos.models import Vencimento

    abertas = (
        contrato.vencimentos.exclude(status=Vencimento.Status.PAGO)
        .exclude(pagamentos__isnull=False)
        .order_by("numero")
    )
    itens = []
    for venc in abertas:
        dias = atraso.dias_de_atraso(venc.data_vencimento, hoje, contrato.estrutura)
        if dias <= 0 and venc.data_vencimento != hoje:
            continue  # ainda não venceu
        itens.append(
            ParcelaACobrar(
                numero=venc.numero,
                data_vencimento=venc.data_vencimento,
                dias_atraso=dias,
                saldo=venc.saldo,
                juros=atraso.juros_acumulados(dias),
            )
        )
    return itens


def montar_agenda_do_dia(hoje: datetime.date | None = None, *, estrutura: str | None = None) -> dict:
    """Contratos a cobrar hoje + totais.

    Devolve um dict com ``hoje``, ``linhas`` (uma por contrato, ordenadas por
    dias de atraso decrescente) e os totais ``total_previsto``, ``n_atraso``
    e ``n_bloqueio``. Cada linha tem ``contrato``, ``situacao``
    (`SituacaoAtraso`), ``vence_hoje``, ``parcela`` e ``a_cobrar``.

    ``estrutura`` filtra pelo tipo de contrato (`Contrato.Estrutura`) — usado
    pelo painel "Cobrar hoje"; o lembrete diário chama sem esse argumento
    (sempre todos os tipos).
    """
    if hoje is None:
        hoje = timezone.localdate()

    contratos = (
        Contrato.objects.exclude(status=Contrato.Status.QUITADO)
        .select_related("cliente")
        .order_by("cliente__nome", "apelido")
    )
    if estrutura:
        contratos = contratos.filter(estrutura=estrutura)

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

        vencimento_aberto = ct.parcela_em_aberto()
        # Usa o saldo real da parcela em aberto, não o valor nominal do
        # contrato: depois de uma baixa parcial, o saldo transportado já
        # ajustou esse valor, e é ele que o Pix automático de fato cobra
        # (ver apps/pagamentos/pix_cora.py) — painel e mensagem têm que bater
        # com o que a Cora realmente gera. Sem vencimento gerado ainda,
        # preserva `None` quando falta `valor_parcela` (o painel mostra "—").
        parcela = vencimento_aberto.saldo if vencimento_aberto else ct.valor_parcela
        a_cobrar = (parcela or Decimal("0.00")) + situacao.juros
        # Várias parcelas em aberto: cobra o conjunto, cada uma com o seu atraso.
        parcelas = parcelas_a_cobrar(ct, hoje)
        if len(parcelas) > 1:
            a_cobrar = sum((p.total for p in parcelas), Decimal("0.00"))
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
                "parcela": parcela,
                "parcelas": parcelas,
                "a_cobrar": a_cobrar,
            }
        )

    linhas.sort(key=lambda linha: linha["situacao"].dias_atraso, reverse=True)

    # Expõe no painel o estado da mensagem do dia sem misturar a regra da
    # agenda com o mecanismo de envio.
    if linhas:
        from apps.pagamentos.models import Cobranca, CobrancaCora

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
            parcela = linha["contrato"].parcela_em_aberto()
            try:
                linha["pix"] = parcela.cobranca_cora if parcela else None
            except CobrancaCora.DoesNotExist:
                linha["pix"] = None

    return {
        "hoje": hoje,
        "linhas": linhas,
        "total_previsto": total_previsto,
        "n_atraso": n_atraso,
        "n_bloqueio": n_bloqueio,
    }
