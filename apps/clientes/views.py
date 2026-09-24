from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.pagamentos.models import Cobranca, CobrancaCora, Pagamento

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
        return qs.order_by("nome")

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
        contratos = list(self.object.contratos.all())
        ctx["contratos"] = contratos
        paineis = [_painel_do_contrato(ct) for ct in contratos]
        ctx["paineis"] = paineis
        ctx["avisos"] = [aviso for painel in paineis for aviso in painel["avisos"]]
        ctx["mensagens"] = Cobranca.objects.filter(contrato__cliente=self.object).select_related(
            "contrato"
        )[:10]
        pagamentos = Pagamento.objects.filter(
            contrato__cliente=self.object
        ).select_related("contrato", "vencimento", "usuario_baixa")
        ctx["pagamentos"] = pagamentos[:50]
        ctx["pagamentos_total"] = pagamentos.count()
        return ctx


def _painel_do_contrato(contrato) -> dict:
    """Tudo que a tela do cliente mostra de um contrato: situação, quanto cobrar,
    estado da cobrança automática da parcela em aberto e os avisos que isso gera."""
    parcela = contrato.parcela_em_aberto()
    situacao = contrato.situacao_atraso()
    pix = getattr(parcela, "cobranca_cora", None) if parcela else None
    saldo = (parcela.saldo if parcela else contrato.valor_parcela) or Decimal("0.00")
    juros = situacao.juros if situacao else Decimal("0.00")

    # Cobrança automática: "suspensa" quando o Pix da parcela foi cancelado.
    if contrato.quitado or parcela is None:
        automatica = None
    elif pix and pix.status == CobrancaCora.Status.CANCELADO:
        automatica = "suspensa"
    elif pix and pix.status == CobrancaCora.Status.PAGO:
        automatica = "paga"
    else:
        automatica = "ativa"

    avisos = []
    if situacao and situacao.alertar_bloqueio:
        avisos.append(
            ("critico", f"{contrato.apelido}: {situacao.dias_atraso} dias de atraso — hora de bloquear o aparelho (ação manual).")
        )
    elif situacao and situacao.dias_atraso:
        avisos.append(
            ("atencao", f"{contrato.apelido}: {situacao.dias_atraso} dia(s) de atraso, juros de R$ {situacao.juros}.")
        )
    if pix and pix.status == CobrancaCora.Status.ERRO:
        avisos.append(("critico", f"{contrato.apelido}: o Pix da parcela {parcela.numero} deu erro ao ser gerado."))
    if automatica == "suspensa":
        avisos.append(("info", f"{contrato.apelido}: cobrança automática suspensa na parcela {parcela.numero}."))

    return {
        "contrato": contrato,
        "situacao": situacao,
        "parcela": parcela,
        "pix": pix,
        "automatica": automatica,
        "saldo": saldo,
        "juros": juros,
        "a_cobrar": saldo + juros,
        "ultima_mensagem": contrato.cobrancas.first(),
        "avisos": avisos,
    }


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
