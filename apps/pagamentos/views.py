"""Painel "Cobrar hoje" (Fase 2 — Modalidade A, base da v1).

Monta a lista de contratos a cobrar no dia: os que estão atrasados (qualquer
estrutura) ou cujo próximo vencimento é hoje. Reaproveita o cálculo da Fase 4
(`Contrato.situacao_atraso`), que hoje trabalha com `proximo_vencimento`.

O disparo do lembrete para a Yslane às 08:30 (Telegram/e-mail) fica para quando
o canal for escolhido — PLANO-DO-PROJETO.md, seção 13. Aqui é só a tela.
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView

from apps.contratos.models import Contrato

from .forms import PagamentoForm
from .models import Pagamento, Vencimento


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


class PagamentoCreateView(LoginRequiredMixin, CreateView):
    """Baixa de um pagamento numa parcela de um contrato."""

    form_class = PagamentoForm
    template_name = "pagamentos/pagamento_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.contrato = get_object_or_404(
            Contrato.objects.select_related("cliente"), pk=kwargs["contrato_pk"]
        )
        if request.user.is_authenticated and self.contrato.quitado:
            messages.info(request, "Contrato quitado — não há mais o que cobrar.")
            return redirect("contratos:detalhe", pk=self.contrato.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["contrato"] = self.contrato
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["contrato"] = self.contrato
        ctx["parcelas_abertas"] = self.contrato.vencimentos.exclude(
            status=Vencimento.Status.PAGO
        ).order_by("numero")
        return ctx

    def form_valid(self, form):
        pagamento = form.save(commit=False)
        pagamento.contrato = self.contrato
        pagamento.usuario_baixa = self.request.user
        pagamento.registrar()
        self.object = pagamento

        venc = pagamento.vencimento
        if venc is not None:
            venc.refresh_from_db()
            messages.success(
                self.request,
                f"Baixa registrada na parcela {venc.numero} — agora "
                f"{venc.get_status_display().lower()}.",
            )
        else:
            messages.success(self.request, "Pagamento registrado.")

        self._avisar_se_tudo_pago()
        return redirect("contratos:detalhe", pk=self.contrato.pk)

    def _avisar_se_tudo_pago(self):
        ct = self.contrato
        if ct.quitado or not ct.num_parcelas:
            return
        pagas = ct.vencimentos.filter(status=Vencimento.Status.PAGO).count()
        if pagas >= ct.num_parcelas:
            messages.info(
                self.request,
                f"Todas as {ct.num_parcelas} parcelas estão pagas. Use o botão "
                "“Marcar como quitado” no detalhe do contrato.",
            )


class PagamentoEstornarView(LoginRequiredMixin, View):
    """Desfaz uma baixa lançada por engano (POST)."""

    def post(self, request, contrato_pk, pk):
        pagamento = get_object_or_404(
            Pagamento.objects.select_related("vencimento"),
            pk=pk,
            contrato_id=contrato_pk,
        )
        numero = pagamento.vencimento.numero if pagamento.vencimento_id else None
        restante_transportado = pagamento.estornar()
        if numero is not None:
            messages.success(request, f"Baixa da parcela {numero} estornada.")
        else:
            messages.success(request, "Pagamento estornado.")
        if restante_transportado:
            messages.warning(
                request,
                "Esta baixa havia transportado saldo para parcelas seguintes. "
                "Confira os valores previstos das próximas parcelas na mão.",
            )
        return redirect("contratos:detalhe", pk=contrato_pk)


class HistoricoPagamentosView(LoginRequiredMixin, ListView):
    """Histórico de baixas — todas, ou de um cliente/contrato via querystring."""

    template_name = "pagamentos/historico.html"
    context_object_name = "pagamentos"
    paginate_by = 50

    def get_queryset(self):
        qs = Pagamento.objects.select_related(
            "contrato__cliente", "vencimento", "usuario_baixa"
        )
        self.cliente_id = self.request.GET.get("cliente", "").strip()
        self.contrato_id = self.request.GET.get("contrato", "").strip()
        if self.cliente_id:
            qs = qs.filter(contrato__cliente_id=self.cliente_id)
        if self.contrato_id:
            qs = qs.filter(contrato_id=self.contrato_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtrado"] = bool(self.cliente_id or self.contrato_id)
        return ctx
