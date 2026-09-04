from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.clientes.models import Cliente

from .forms import ContratoForm, DocumentoContratoForm
from .models import Contrato


def _avisar_se_parcela_nao_bate(request, contrato):
    """Aviso não-bloqueante quando ``valor_parcela × num_parcelas`` diverge do
    valor total (o cálculo da parcela é feito fora do sistema — seção 5 do plano)."""
    if contrato.parcelas_conferem is False:
        soma = f"{contrato.total_das_parcelas:.2f}".replace(".", ",")
        total = f"{contrato.valor_total:.2f}".replace(".", ",")
        messages.warning(
            request,
            f"Parcela × nº de parcelas dá R$ {soma}, "
            f"diferente do valor total (R$ {total}). Confira os números.",
        )


class ContratoListView(LoginRequiredMixin, ListView):
    model = Contrato
    template_name = "contratos/lista.html"
    context_object_name = "contratos"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente").order_by("cliente__nome", "apelido")
        self.status = self.request.GET.get("status", "").strip()
        if not self.status:
            return qs
        # O filtro trabalha com o status CALCULADO hoje (status_efetivo), o
        # mesmo que a tela mostra — não com o `status` salvo, que só é
        # atualizado quando o job diário da Fase 2 rodar `sincronizar_status`.
        # São poucos contratos; filtrar em memória é aceitável por enquanto.
        return [ct for ct in qs if ct.status_efetivo == self.status]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_atual"] = self.status
        ctx["status_opcoes"] = Contrato.Status.choices
        return ctx


class ContratoDetailView(LoginRequiredMixin, DetailView):
    model = Contrato
    template_name = "contratos/detalhe.html"
    context_object_name = "contrato"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("cliente")
            .prefetch_related(
                "documentos",
                "vencimentos",
                "pagamentos__vencimento",
                "pagamentos__usuario_baixa",
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_documento"] = DocumentoContratoForm()
        contrato = self.object
        vencimentos = list(contrato.vencimentos.all())
        pagas = sum(1 for v in vencimentos if v.status == v.Status.PAGO)
        ctx["pode_quitar"] = (
            not contrato.quitado
            and bool(contrato.num_parcelas)
            and pagas >= contrato.num_parcelas
        )
        return ctx


class ContratoCreateView(LoginRequiredMixin, CreateView):
    model = Contrato
    form_class = ContratoForm
    template_name = "contratos/form.html"

    def get_initial(self):
        initial = super().get_initial()
        cliente_id = self.request.GET.get("cliente")
        if cliente_id:
            initial["cliente"] = get_object_or_404(Cliente, pk=cliente_id)
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Contrato cadastrado.")
        _avisar_se_parcela_nao_bate(self.request, self.object)
        return response

    def get_success_url(self):
        return reverse("contratos:detalhe", args=[self.object.pk])


class ContratoUpdateView(LoginRequiredMixin, UpdateView):
    model = Contrato
    form_class = ContratoForm
    template_name = "contratos/form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Contrato atualizado.")
        _avisar_se_parcela_nao_bate(self.request, self.object)
        return response

    def get_success_url(self):
        return reverse("contratos:detalhe", args=[self.object.pk])


class ContratoQuitarView(LoginRequiredMixin, View):
    """Marca o contrato como quitado (ação manual da Yslane — POST).

    A baixa nunca quita sozinha (decisão do Alisson); aqui o contrato passa a
    `quitado`, para de cobrar e ganha a data prevista de quitação calculada.
    """

    def post(self, request, pk):
        contrato = get_object_or_404(Contrato, pk=pk)
        if contrato.quitado:
            messages.info(request, "Este contrato já estava quitado.")
        else:
            contrato.status = Contrato.Status.QUITADO
            contrato.quitado_em = timezone.localdate()
            contrato.save(update_fields=["status", "quitado_em", "atualizado_em"])
            contrato.atualizar_data_prevista_quitacao()
            messages.success(request, "Contrato marcado como quitado. A cobrança para aqui.")
        return redirect("contratos:detalhe", pk=pk)


class DocumentoCreateView(LoginRequiredMixin, CreateView):
    form_class = DocumentoContratoForm
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        self.contrato = get_object_or_404(Contrato, pk=kwargs["contrato_pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.contrato = self.contrato
        form.instance.enviado_por = self.request.user
        form.save()
        messages.success(self.request, "Documento anexado.")
        return redirect("contratos:detalhe", pk=self.contrato.pk)

    def form_invalid(self, form):
        messages.error(self.request, "Não foi possível anexar o documento. Verifique o arquivo.")
        return redirect("contratos:detalhe", pk=self.contrato.pk)
