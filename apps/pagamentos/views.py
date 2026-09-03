"""Painel "Cobrar hoje" (Fase 2 — Modalidade A, base da v1).

Monta a lista de contratos a cobrar no dia: os que estão atrasados (qualquer
estrutura) ou cujo próximo vencimento é hoje. Reaproveita o cálculo da Fase 4
(`Contrato.situacao_atraso`), que hoje trabalha com `proximo_vencimento`.

O disparo do lembrete para a Yslane às 08:30 (Telegram/e-mail) fica para quando
o canal for escolhido — PLANO-DO-PROJETO.md, seção 13. Aqui é só a tela.
"""

from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from apps.contratos.models import Contrato


class CobrarHojeView(LoginRequiredMixin, TemplateView):
    template_name = "pagamentos/cobrar_hoje.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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
                continue  # sem próximo vencimento — nada a cobrar ainda
            vence_hoje = ct.proximo_vencimento == hoje
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

        ctx.update(
            hoje=hoje,
            linhas=linhas,
            total_previsto=total_previsto,
            n_atraso=n_atraso,
            n_bloqueio=n_bloqueio,
        )
        return ctx
