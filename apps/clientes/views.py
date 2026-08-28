from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import ClienteForm
from .models import Cliente


class ClienteListView(LoginRequiredMixin, ListView):
    model = Cliente
    template_name = "clientes/lista.html"
    context_object_name = "clientes"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().annotate(num_contratos=Count("contratos"))
        self.busca = self.request.GET.get("q", "").strip()
        if self.busca:
            qs = qs.filter(Q(nome__icontains=self.busca) | Q(cpf__icontains=self.busca))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["busca"] = self.busca
        return ctx


class ClienteDetailView(LoginRequiredMixin, DetailView):
    model = Cliente
    template_name = "clientes/detalhe.html"
    context_object_name = "cliente"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["contratos"] = self.object.contratos.all()
        return ctx


class ClienteCreateView(LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "clientes/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Cliente cadastrado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("clientes:detalhe", args=[self.object.pk])


class ClienteUpdateView(LoginRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "clientes/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Cliente atualizado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("clientes:detalhe", args=[self.object.pk])
