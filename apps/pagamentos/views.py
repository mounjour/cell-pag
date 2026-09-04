"""Painel "Cobrar hoje" (Fase 2 — Modalidade A, base da v1).

A lista de contratos a cobrar no dia mora em `apps.pagamentos.agenda` (usada
também pelo lembrete diário — `apps.pagamentos.lembrete`). O disparo do
lembrete no WhatsApp da Yslane às 08:30 já tem o texto e o job prontos; falta
só a conta WhatsApp Business para o envio de verdade (ver `lembrete.py`).
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView
from django.utils import timezone

from apps.contratos.models import Contrato

from .agenda import montar_agenda_do_dia
from .forms import PagamentoForm
from .models import CobrancaPix, Pagamento, Vencimento


class CobrarHojeView(LoginRequiredMixin, TemplateView):
    template_name = "pagamentos/cobrar_hoje.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(montar_agenda_do_dia())
        return ctx


class PixPainelView(LoginRequiredMixin, TemplateView):
    template_name = "pagamentos/pix_painel.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        cobrancas = list(
            CobrancaPix.objects.select_related("vencimento__contrato__cliente")
            .filter(
                Q(status__in=[
                    CobrancaPix.Status.PENDENTE,
                    CobrancaPix.Status.ABERTO,
                    CobrancaPix.Status.VENCIDO,
                    CobrancaPix.Status.ERRO,
                ])
                | Q(pago_em__date=hoje)
            )
            .order_by("status", "data_vencimento", "vencimento__contrato__cliente__nome")
        )
        ctx.update(
            hoje=hoje,
            cobrancas_pix=cobrancas,
            total=len(cobrancas),
            pagas=sum(c.status == CobrancaPix.Status.PAGO for c in cobrancas),
            nao_pagas=sum(c.status == CobrancaPix.Status.VENCIDO for c in cobrancas),
            aguardando=sum(c.status in {CobrancaPix.Status.PENDENTE, CobrancaPix.Status.ABERTO} for c in cobrancas),
            erros=sum(c.status == CobrancaPix.Status.ERRO for c in cobrancas),
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
