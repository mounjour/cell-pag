import re
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, ProtectedError, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.pagamentos.models import Cobranca, CobrancaCora, Pagamento

from apps.contratos.models import Contrato

from .forms import ClienteForm
from .models import Cliente


class ClienteListView(LoginRequiredMixin, ListView):
    model = Cliente
    template_name = "clientes/lista.html"
    context_object_name = "clientes"
    paginate_by = 20

    def get_queryset(self):
        self.arquivados = self.request.GET.get("arquivados") == "1"
        qs = super().get_queryset().annotate(num_contratos=Count("contratos"))
        qs = qs.filter(ativo=not self.arquivados)
        self.busca = self.request.GET.get("q", "").strip()
        if self.busca:
            qs = qs.filter(Q(nome__icontains=self.busca) | Q(cpf__icontains=self.busca))
        return qs.order_by("nome")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["arquivados"] = self.arquivados
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


class ClienteArquivarView(LoginRequiredMixin, View):
    """Arquiva o cliente (POST) — some da lista principal, mas o cadastro e o
    histórico continuam intactos. É o caminho recomendado quando os contratos
    de um cliente terminam, já que apagar de vez é bloqueado enquanto houver
    qualquer contrato (mesmo quitado) — ver `Cliente.pode_ser_excluido`."""

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        cliente.ativo = False
        cliente.save(update_fields=["ativo", "atualizado_em"])
        messages.success(
            request,
            f"{cliente.nome} arquivado. Some da lista principal, mas o histórico continua acessível aqui.",
        )
        return redirect("clientes:detalhe", pk=pk)


class ClienteReativarView(LoginRequiredMixin, View):
    """Desfaz o arquivamento (POST)."""

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        cliente.ativo = True
        cliente.save(update_fields=["ativo", "atualizado_em"])
        messages.success(request, f"{cliente.nome} reativado.")
        return redirect("clientes:detalhe", pk=pk)


class ClienteExcluirView(LoginRequiredMixin, View):
    """Apaga o cliente de vez (POST) — só funciona sem nenhum contrato.

    Com contrato (mesmo quitado), o banco protege o histórico financeiro
    (`Contrato.cliente` é `on_delete=PROTECT`) e a exclusão é recusada com uma
    mensagem explicando para usar "Arquivar" em vez de excluir.
    """

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        nome = cliente.nome
        try:
            cliente.delete()
        except ProtectedError:
            messages.error(
                request,
                f"{nome} tem contrato cadastrado (mesmo quitado) e não pode ser excluído — "
                "isso apagaria o histórico de pagamentos. Use “Arquivar” para tirá-lo da lista "
                "principal sem perder o histórico.",
            )
            return redirect("clientes:detalhe", pk=pk)
        messages.success(request, f"{nome} excluído.")
        return redirect("clientes:lista")


def _painel_do_contrato(contrato) -> dict:
    """Tudo que a tela do cliente mostra de um contrato: situação, quanto cobrar,
    estado da cobrança automática da parcela em aberto e os avisos que isso gera."""
    from apps.pagamentos.agenda import resumo_cobranca

    resumo = resumo_cobranca(contrato)
    parcela = contrato.parcela_em_aberto()
    situacao = contrato.situacao_atraso()
    pix = getattr(parcela, "cobranca_cora", None) if parcela else None
    saldo = resumo["principal"]
    juros = resumo["juros"]

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
            ("atencao", f"{contrato.apelido}: {situacao.dias_atraso} dia(s) de atraso; confira abaixo o total das parcelas e dos juros.")
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
        "resumo": resumo,
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


BUSCA_MINIMO = 2


def pesquisar(q: str, limite: int):
    """Busca única do menu: clientes (nome, CPF) e contratos (apelido,
    aparelho, IMEI, nº do contrato, nome do cliente). Devolve
    ``(clientes, contratos)``; vazio se ``q`` for curta demais."""
    q = q.strip()
    if len(q) < BUSCA_MINIMO:
        return [], []
    digitos = "".join(c for c in q if c.isdigit())
    filtro_cliente = Q(nome__icontains=q)
    if len(digitos) >= 3:  # CPF é guardado só com dígitos
        filtro_cliente |= Q(cpf__icontains=digitos)
    clientes = list(
        Cliente.objects.filter(filtro_cliente)
        .annotate(num_contratos=Count("contratos", distinct=True))
        .order_by("-ativo", "nome")[:limite]
    )
    filtro_contrato = (
        Q(apelido__icontains=q)
        | Q(aparelho_modelo__icontains=q)
        | Q(imei__icontains=q)
        | Q(cliente__nome__icontains=q)
    )
    numero = re.fullmatch(r"(?i)ct-?0*(\d+)", q)  # "CT-0004" -> contrato 4
    if numero:
        filtro_contrato |= Q(pk=int(numero.group(1)))
    contratos = list(
        Contrato.objects.filter(filtro_contrato)
        .select_related("cliente")
        .order_by("cliente__nome", "apelido")[:limite]
    )
    return clientes, contratos


class BuscaGlobalView(LoginRequiredMixin, TemplateView):
    """Página de resultados da busca do menu."""

    template_name = "busca.html"
    LIMITE = 20

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        clientes, contratos = pesquisar(q, self.LIMITE)
        ctx.update(
            q=q,
            curta=0 < len(q) < BUSCA_MINIMO,
            clientes=clientes,
            contratos=contratos,
            total=len(clientes) + len(contratos),
        )
        return ctx


class BuscaSugestoesView(LoginRequiredMixin, View):
    """Sugestões da busca enquanto se digita (JSON, poucos itens)."""

    LIMITE = 5

    def get(self, request):
        q = request.GET.get("q", "").strip()
        clientes, contratos = pesquisar(q, self.LIMITE)
        return JsonResponse(
            {
                "q": q,
                "clientes": [
                    {
                        "titulo": c.nome,
                        "detalhe": c.cpf_formatado,
                        "arquivado": not c.ativo,
                        "url": reverse("clientes:detalhe", args=[c.pk]),
                    }
                    for c in clientes
                ],
                "contratos": [
                    {
                        "titulo": f"{ct.numero_interno} · {ct.apelido}",
                        "detalhe": ct.cliente.nome,
                        "arquivado": False,
                        "url": reverse("contratos:detalhe", args=[ct.pk]),
                    }
                    for ct in contratos
                ],
            }
        )
