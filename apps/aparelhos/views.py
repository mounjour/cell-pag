from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.contratos.models import Contrato

from .forms import AparelhoForm
from .models import Aparelho


class AparelhoListView(LoginRequiredMixin, ListView):
    model = Aparelho
    template_name = "aparelhos/lista.html"
    context_object_name = "aparelhos"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        self.busca = self.request.GET.get("q", "").strip()
        if self.busca:
            qs = qs.filter(Q(modelo__icontains=self.busca) | Q(imei__icontains=self.busca))
        self.status = self.request.GET.get("status", "").strip()
        if self.status == Aparelho.Status.DISPONIVEL:
            qs = qs.filter(contrato__isnull=True)
        elif self.status == Aparelho.Status.ALOCADO:
            qs = qs.filter(contrato__isnull=False).exclude(contrato__status=Contrato.Status.QUITADO)
        elif self.status == Aparelho.Status.VENDIDO:
            qs = qs.filter(contrato__status=Contrato.Status.QUITADO)
        return qs.select_related("contrato__cliente")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["busca"] = self.busca
        ctx["status_atual"] = self.status
        ctx["status_opcoes"] = Aparelho.Status.choices
        ctx["total_disponiveis"] = Aparelho.objects.filter(contrato__isnull=True).count()
        return ctx


class AparelhoDetailView(LoginRequiredMixin, DetailView):
    model = Aparelho
    template_name = "aparelhos/detalhe.html"
    context_object_name = "aparelho"

    def get_queryset(self):
        return super().get_queryset().select_related("contrato__cliente")


class AparelhoCreateView(LoginRequiredMixin, CreateView):
    model = Aparelho
    form_class = AparelhoForm
    template_name = "aparelhos/form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Aparelho cadastrado no estoque.")
        return response

    def get_success_url(self):
        return reverse("aparelhos:detalhe", args=[self.object.pk])


class AparelhoUpdateView(LoginRequiredMixin, UpdateView):
    model = Aparelho
    form_class = AparelhoForm
    template_name = "aparelhos/form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Aparelho atualizado.")
        return response

    def get_success_url(self):
        return reverse("aparelhos:detalhe", args=[self.object.pk])


class AparelhoExcluirView(LoginRequiredMixin, View):
    """Apaga o aparelho do estoque (POST) — só funciona se não estiver alocado/vendido.

    Um aparelho com contrato está `on_delete=PROTECT` no contrato: apagar perderia
    o vínculo do histórico. A mensagem orienta a não usar exclusão nesse caso.
    """

    def post(self, request, pk):
        aparelho = get_object_or_404(Aparelho, pk=pk)
        nome = str(aparelho)
        try:
            aparelho.delete()
        except ProtectedError:
            messages.error(
                request,
                f"{nome} está vinculado a um contrato e não pode ser excluído do estoque.",
            )
            return redirect("aparelhos:detalhe", pk=pk)
        messages.success(request, f"{nome} excluído do estoque.")
        return redirect("aparelhos:lista")
