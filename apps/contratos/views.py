from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.clientes.models import Cliente

from .forms import ContratoForm, DocumentoContratoForm
from .models import Contrato


class ContratoListView(LoginRequiredMixin, ListView):
    model = Contrato
    template_name = "contratos/lista.html"
    context_object_name = "contratos"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente")
        self.status = self.request.GET.get("status", "").strip()
        if self.status:
            qs = qs.filter(status=self.status)
        return qs

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
        return super().get_queryset().select_related("cliente").prefetch_related("documentos")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_documento"] = DocumentoContratoForm()
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
        messages.success(self.request, "Contrato cadastrado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("contratos:detalhe", args=[self.object.pk])


class ContratoUpdateView(LoginRequiredMixin, UpdateView):
    model = Contrato
    form_class = ContratoForm
    template_name = "contratos/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Contrato atualizado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("contratos:detalhe", args=[self.object.pk])


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
