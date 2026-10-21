from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.contratos.models import Contrato

from . import bloqueios, importacao
from .forms import AparelhoForm, ImportarAparelhosForm
from .models import Aparelho, BloqueioAparelho


CHAVE_SESSAO_IMPORTACAO = "importacao_aparelhos_csv"


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


class AparelhoImportarView(LoginRequiredMixin, TemplateView):
    """Envia o CSV e mostra a prévia (quais aparelhos entram e quais ficam de fora, com o motivo)."""

    template_name = "aparelhos/importar.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("form", ImportarAparelhosForm())
        ctx.setdefault("linhas", None)
        return ctx

    def post(self, request, *args, **kwargs):
        form = ImportarAparelhosForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        linhas, erro = importacao.analisar(form.cleaned_data["arquivo"].read())
        if erro:
            request.session.pop(CHAVE_SESSAO_IMPORTACAO, None)
            return self.render_to_response(self.get_context_data(form=form, erro=erro))
        request.session[CHAVE_SESSAO_IMPORTACAO] = linhas
        return self.render_to_response(
            self.get_context_data(form=ImportarAparelhosForm(), linhas=linhas, resumo=importacao.resumir(linhas))
        )


class AparelhoImportarConfirmarView(LoginRequiredMixin, View):
    """Cria os aparelhos da prévia (só as linhas válidas e novas)."""

    def post(self, request):
        linhas = request.session.pop(CHAVE_SESSAO_IMPORTACAO, None)
        if not linhas:
            messages.error(request, "A prévia expirou. Envie o arquivo de novo.")
            return redirect("aparelhos:importar")
        criados = importacao.gravar(linhas)
        plural = "s" if criados != 1 else ""
        messages.success(request, f"{criados} aparelho{plural} cadastrado{plural} no estoque.")
        return redirect("aparelhos:lista")


def _voltar_ou(request, padrao):
    """Volta para a página de onde veio o clique (só endereços do próprio sistema)."""
    from django.utils.http import url_has_allowed_host_and_scheme

    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, {request.get_host()}, request.is_secure()):
        return redirect(destino)
    return redirect(padrao)


class BloqueiosView(LoginRequiredMixin, TemplateView):
    """Controle dos aparelhos bloqueados por atraso: o que bloquear, o que está bloqueado e o que liberar."""

    template_name = "aparelhos/bloqueios.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        painel = bloqueios.montar_painel()
        ctx.update(painel)
        if painel["a_bloquear"]:
            n = len(painel["a_bloquear"])
            messages.warning(
                self.request,
                f"{n} aparelho{'s' if n != 1 else ''} com 8 dias ou mais de atraso "
                f"{'esperam' if n != 1 else 'espera'} bloqueio.",
            )
        if painel["para_desbloquear"]:
            n = len(painel["para_desbloquear"])
            messages.info(
                self.request,
                f"{n} cliente{'s' if n != 1 else ''} regularizou{'aram' if n != 1 else ''}: "
                f"libere {'os aparelhos' if n != 1 else 'o aparelho'}.",
            )
        return ctx


class BloquearView(LoginRequiredMixin, View):
    """Registra que o aparelho do contrato foi bloqueado (POST)."""

    def post(self, request, contrato_pk):
        from apps.contratos.models import Contrato
        from apps.pagamentos import badge

        contrato = get_object_or_404(Contrato, pk=contrato_pk)
        if contrato.quitado:
            messages.error(request, "Contrato quitado: o aparelho não deve ser bloqueado.")
        elif contrato.bloqueios.filter(desbloqueado_em__isnull=True).exists():
            messages.info(request, "Este aparelho já está registrado como bloqueado.")
        else:
            BloqueioAparelho.objects.create(
                contrato=contrato, bloqueado_por=request.user, observacao=request.POST.get("observacao", "").strip()[:200]
            )
            badge.invalidar()
            messages.success(request, f"Bloqueio registrado: {contrato.apelido} de {contrato.cliente.nome}.")
        return _voltar_ou(request, "aparelhos:bloqueios")


class DesbloquearView(LoginRequiredMixin, View):
    """Registra que o aparelho foi liberado (POST)."""

    def post(self, request, pk):
        from apps.pagamentos import badge

        bloqueio = get_object_or_404(BloqueioAparelho.objects.select_related("contrato__cliente"), pk=pk)
        if bloqueio.desbloqueado_em:
            messages.info(request, "Este aparelho já estava liberado.")
        else:
            bloqueio.desbloqueado_em = timezone.now()
            bloqueio.desbloqueado_por = request.user
            bloqueio.save(update_fields=["desbloqueado_em", "desbloqueado_por"])
            badge.invalidar()
            messages.success(
                request, f"Aparelho liberado: {bloqueio.contrato.apelido} de {bloqueio.contrato.cliente.nome}."
            )
        return _voltar_ou(request, "aparelhos:bloqueios")
