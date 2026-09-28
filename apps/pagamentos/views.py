"""Painel "Cobrar hoje" (Fase 2 — Modalidade A, base da v1).

A lista de contratos a cobrar no dia mora em `apps.pagamentos.agenda` (usada
também pelo lembrete diário — `apps.pagamentos.lembrete`). O disparo do
lembrete no WhatsApp da Yslane às 08:30 já tem o texto e o job prontos; falta
só a conta WhatsApp Business para o envio de verdade (ver `lembrete.py`).
"""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView
from django.utils import timezone

from apps.arquivos import servir_anexo
from apps.paginacao import paginar
from apps.contratos.models import Contrato

from . import cora_api
from .agenda import montar_agenda_do_dia
from .forms import PagamentoForm
from .comprovantes import conferir_na_cora
from .limpeza import encerrar_cobranca_automatica
from .models import CobrancaCora, ComprovanteRecebido, Pagamento, Vencimento
from .pix_cora import (
    parcelas_do_pix,
    CancelamentoRecusado,
    cancelar_cobranca,
    retomar_cobranca,
    suspender_cobranca,
)


logger = logging.getLogger("pagamentos.views")

POR_PAGINA_COBRAR_HOJE = 20
POR_PAGINA_PIX = 25


def _agenda_paginada(request, estrutura):
    """Agenda do dia com só uma página de ``linhas``; os totais são do dia todo."""
    agenda = montar_agenda_do_dia(estrutura=estrutura or None)
    pagina = paginar(request, agenda["linhas"], POR_PAGINA_COBRAR_HOJE)
    agenda["linhas"] = list(pagina["page_obj"].object_list)
    agenda["total_linhas"] = pagina["paginator"].count
    return {**agenda, **pagina}


class CobrarHojeView(LoginRequiredMixin, TemplateView):
    template_name = "pagamentos/cobrar_hoje.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        estrutura = self.request.GET.get("estrutura", "").strip()
        ctx.update(_agenda_paginada(self.request, estrutura))
        ctx["estrutura_atual"] = estrutura
        ctx["estrutura_opcoes"] = Contrato.Estrutura.choices
        return ctx


def _rotulo_parcelas(cobranca, hoje):
    """"3" para um Pix de uma parcela; "1, 2, 3" para o Pix pelo total.

    Pix em aberto: as parcelas vencidas que ele cobra hoje. Pix já pago: se
    entrou mais do que a parcela valia, o resto abateu as seguintes.
    """
    numero = cobranca.vencimento.numero
    if cobranca.status == CobrancaCora.Status.PAGO:
        maior = cobranca.total_pago > cobranca.vencimento.valor_previsto
        return f"{numero} e seguintes" if maior else str(numero)
    numeros = [p.numero for p in parcelas_do_pix(cobranca.vencimento, hoje)]
    return ", ".join(str(n) for n in numeros) if numeros else str(numero)


class PixPainelView(LoginRequiredMixin, TemplateView):
    template_name = "pagamentos/pix_painel.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        cobrancas = list(
            CobrancaCora.objects.select_related("vencimento__contrato__cliente")
            .filter(
                Q(status__in=[
                    CobrancaCora.Status.PENDENTE,
                    CobrancaCora.Status.ABERTO,
                    CobrancaCora.Status.VENCIDO,
                    CobrancaCora.Status.ERRO,
                ])
                | Q(pago_em__date=hoje)
            )
            .order_by("status", "data_vencimento", "vencimento__contrato__cliente__nome")
        )
        pagina = paginar(self.request, cobrancas, POR_PAGINA_PIX)
        for c in pagina["page_obj"].object_list:
            c.rotulo_parcelas = _rotulo_parcelas(c, hoje)
        ctx.update(pagina)
        ctx.update(
            hoje=hoje,
            cobrancas_cora=list(pagina["page_obj"].object_list),
            total=len(cobrancas),
            pagas=sum(c.status == CobrancaCora.Status.PAGO for c in cobrancas),
            nao_pagas=sum(c.status == CobrancaCora.Status.VENCIDO for c in cobrancas),
            aguardando=sum(c.status in {CobrancaCora.Status.PENDENTE, CobrancaCora.Status.ABERTO} for c in cobrancas),
            erros=sum(c.status == CobrancaCora.Status.ERRO for c in cobrancas),
            duplicadas=CobrancaCora.objects.select_related("vencimento__contrato__cliente")
            .filter(duplicada=True, duplicidade_resolvida_em__isnull=True)
            .order_by("pago_em"),
            comprovantes=ComprovanteRecebido.objects.select_related("cliente", "vencimento__contrato")
            .filter(status=ComprovanteRecebido.Status.AGUARDANDO)
            .order_by("recebido_em"),
        )
        return ctx


class PixCancelarView(LoginRequiredMixin, View):
    """Cancela o Pix (fatura da Cora) de uma parcela e suspende a cobrança
    automática dela (POST). Nunca cancela um Pix já pago."""

    def post(self, request, pk):
        cobranca = get_object_or_404(
            CobrancaCora.objects.select_related("vencimento__contrato__cliente"), pk=pk
        )
        parcela = f"parcela {cobranca.vencimento.numero} de {cobranca.vencimento.contrato.cliente.nome}"
        try:
            cancelar_cobranca(cobranca)
        except CancelamentoRecusado as exc:
            messages.error(request, f"{exc} ({parcela})")
        except cora_api.CoraErro as exc:
            messages.error(
                request, f"Não consegui cancelar o Pix da {parcela}: {exc} Nada foi alterado."
            )
        else:
            messages.success(
                request,
                f"Pix da {parcela} cancelado. A cobrança automática dessa parcela ficou suspensa.",
            )
        return _voltar_para_origem(request)


class CobrancaSuspenderView(LoginRequiredMixin, View):
    """Suspende a cobrança automática de uma parcela (POST) — com ou sem Pix já
    gerado. A rotina diária deixa de cobrá-la até alguém retomar."""

    def post(self, request, vencimento_pk):
        vencimento = get_object_or_404(
            Vencimento.objects.select_related("contrato__cliente"), pk=vencimento_pk
        )
        parcela = f"parcela {vencimento.numero} de {vencimento.contrato.cliente.nome}"
        try:
            suspender_cobranca(vencimento)
        except CancelamentoRecusado as exc:
            messages.error(request, f"{exc} ({parcela})")
        except cora_api.CoraErro as exc:
            messages.error(
                request, f"Não consegui suspender a cobrança da {parcela}: {exc} Nada foi alterado."
            )
        else:
            messages.success(
                request,
                f"Cobrança automática da {parcela} suspensa. Nenhuma mensagem nem Pix será enviado até você retomar.",
            )
        return _voltar_para_origem(request)


class PixDuplicidadeResolvidaView(LoginRequiredMixin, View):
    """Marca como resolvida (valor devolvido ao cliente) uma duplicidade de Pix (POST)."""

    def post(self, request, pk):
        cobranca = get_object_or_404(
            CobrancaCora.objects.select_related("vencimento__contrato__cliente"), pk=pk, duplicada=True
        )
        if cobranca.duplicidade_resolvida_em is None:
            cobranca.duplicidade_resolvida_em = timezone.now()
            cobranca.save(update_fields=["duplicidade_resolvida_em", "atualizado_em"])
        cliente = cobranca.vencimento.contrato.cliente.nome
        messages.success(request, f"Duplicidade de {cliente} marcada como resolvida.")
        return _voltar_para_origem(request)


class ComprovanteConferirView(LoginRequiredMixin, View):
    """Consulta a Cora agora sobre o comprovante enviado pelo cliente (POST)."""

    def post(self, request, pk):
        comprovante = get_object_or_404(
            ComprovanteRecebido.objects.select_related("cliente", "vencimento"), pk=pk
        )
        nome = comprovante.cliente.nome
        if comprovante.status != ComprovanteRecebido.Status.AGUARDANDO:
            messages.info(request, f"O comprovante de {nome} já foi resolvido.")
        elif not conferir_na_cora(comprovante):
            messages.warning(
                request,
                f"Não consegui consultar a Cora para {nome} (sem Pix gerado ou Cora fora do ar). "
                "Confira a conta e, se o dinheiro entrou, registre o pagamento.",
            )
        else:
            comprovante.refresh_from_db()
            if comprovante.status == ComprovanteRecebido.Status.CONFIRMADO:
                messages.success(request, f"Pix de {nome} confirmado pela Cora — baixa dada e cliente avisado.")
            else:
                messages.warning(request, f"O Pix de {nome} ainda não caiu na Cora.")
        return _voltar_para_origem(request)


class ComprovanteDescartarView(LoginRequiredMixin, View):
    """Descarta um arquivo que não era comprovante (foto qualquer etc.) (POST)."""

    def post(self, request, pk):
        comprovante = get_object_or_404(ComprovanteRecebido, pk=pk)
        if comprovante.status == ComprovanteRecebido.Status.AGUARDANDO:
            comprovante.status = ComprovanteRecebido.Status.DESCARTADO
            comprovante.resolvido_em = timezone.now()
            comprovante.resolvido_por = request.user
            comprovante.save(update_fields=["status", "resolvido_em", "resolvido_por"])
            messages.success(request, "Aviso descartado.")
        return _voltar_para_origem(request)


class CobrancaRetomarView(LoginRequiredMixin, View):
    """Volta a cobrar automaticamente uma parcela suspensa (POST)."""

    def post(self, request, pk):
        cobranca = get_object_or_404(
            CobrancaCora.objects.select_related("vencimento__contrato__cliente"), pk=pk
        )
        parcela = f"parcela {cobranca.vencimento.numero} de {cobranca.vencimento.contrato.cliente.nome}"
        try:
            retomar_cobranca(cobranca)
        except CancelamentoRecusado as exc:
            messages.error(request, f"{exc} ({parcela})")
        else:
            messages.success(
                request,
                f"Cobrança automática da {parcela} retomada. Um novo Pix é gerado na próxima rotina.",
            )
        return _voltar_para_origem(request)


def _voltar_para_origem(request):
    """Redireciona para o `next` do formulário — só se for uma página deste site."""
    destino = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        destino = reverse("pagamentos:pix_painel")
    return redirect(destino)


class PagamentoCreateView(LoginRequiredMixin, CreateView):
    """Baixa de um pagamento numa parcela de um contrato.

    Aberta tanto como página cheia (link direto) quanto dentro do diálogo
    "Registrar" do painel Cobrar hoje (via htmx — `apps/pagamentos/static ...
    js/cobrar_hoje.js` + `templates/pagamentos/_pagamento_form_conteudo.html`).
    Quando a requisição vem do htmx, usa o mesmo conteúdo sem o `base.html`
    (cabeçalho/nav), e a baixa bem-sucedida não redireciona — devolve o
    painel "Cobrar hoje" e as mensagens atualizados via troca fora-de-banda
    (`hx-swap-oob`), pra fechar o diálogo sem recarregar a página.
    """

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

    def _is_htmx(self):
        return self.request.headers.get("HX-Request") == "true"

    def get_template_names(self):
        if self._is_htmx():
            return ["pagamentos/_pagamento_form_conteudo.html"]
        return [self.template_name]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["contrato"] = self.contrato
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["contrato"] = self.contrato
        ctx["em_dialog"] = self._is_htmx()
        # Segue no querystring do hx-post do formulário (ver
        # _pagamento_form_conteudo.html) pra _resposta_htmx_sucesso saber
        # qual filtro do Cobrar hoje reaplicar na troca fora-de-banda.
        ctx["estrutura_atual"] = self.request.GET.get("estrutura", "")
        ctx["parcelas_abertas"] = self.contrato.vencimentos.exclude(
            status=Vencimento.Status.PAGO
        ).order_by("numero")
        # Pode haver parcela "em aberto" pra mostrar (parcial) sem nenhuma
        # selecionável no formulário — todas já com baixa, saldo ainda não
        # repassado pra próxima (ver Contrato.parcela_em_aberto). Distingue
        # esse caso de "não há mais nada a cobrar" no template.
        ctx["pode_registrar"] = ctx["form"].fields["vencimento"].queryset.exists()
        situacao = self.contrato.situacao_atraso()
        ctx["juros_ate_hoje"] = situacao.juros if situacao else None
        return ctx

    def form_invalid(self, form):
        response = super().form_invalid(form)
        if self._is_htmx():
            # 2xx faria o htmx tratar a resposta como sucesso e fechar o
            # diálogo mesmo com o formulário inválido (ver static/js/cobrar_hoje.js).
            response.status_code = 422
        return response

    def form_valid(self, form):
        pagamento = form.save(commit=False)
        pagamento.contrato = self.contrato
        pagamento.usuario_baixa = self.request.user
        pagamento.registrar()
        self.object = pagamento
        self._encerrar_cobranca_automatica(pagamento)

        if pagamento.juros_pago:
            juros_fmt = f"{pagamento.juros_pago:.2f}".replace(".", ",")
            juros_txt = f" + R$ {juros_fmt} de juros"
        else:
            juros_txt = ""
        venc = pagamento.vencimento
        if venc is not None:
            venc.refresh_from_db()
            messages.success(
                self.request,
                f"Pagamento registrado na parcela {venc.numero}{juros_txt} — agora "
                f"{venc.get_status_display().lower()}.",
            )
        else:
            messages.success(self.request, f"Pagamento registrado{juros_txt}.")

        self._avisar_se_tudo_pago()

        if self._is_htmx():
            return self._resposta_htmx_sucesso()
        return redirect("contratos:detalhe", pk=self.contrato.pk)

    def _encerrar_cobranca_automatica(self, pagamento):
        """Cancela o Pix em aberto e resolve a mensagem de cobrança já enviada.
        Nunca desfaz o pagamento: qualquer falha vira um aviso na tela."""
        try:
            avisos = encerrar_cobranca_automatica(pagamento)
        except Exception:  # noqa: BLE001 — o pagamento já foi salvo; só avisa
            logger.exception("Falha ao encerrar a cobrança automática do pagamento %s", pagamento.pk)
            avisos = [(
                "warning",
                "O pagamento foi registrado, mas não consegui encerrar a cobrança automática. "
                "Confira o Pix no painel Pix e a mensagem enviada ao cliente.",
            )]
        for nivel, texto in avisos:
            getattr(messages, nivel)(self.request, texto)

    def _resposta_htmx_sucesso(self):
        """Painel "Cobrar hoje" e mensagens atualizados via troca fora-de-banda.

        O corpo do diálogo (alvo normal da requisição) fica vazio — o
        listener `htmx:afterRequest` em static/js/cobrar_hoje.js fecha o
        diálogo assim que a resposta chega, então o vazio nunca aparece na
        tela.
        """
        estrutura = self.request.GET.get("estrutura", "").strip()
        painel_html = render_to_string(
            "pagamentos/_cobrar_hoje_painel.html",
            {
                **_agenda_paginada(self.request, estrutura),
                "oob": True,
                "estrutura_atual": estrutura,
            },
            request=self.request,
        )
        mensagens_html = render_to_string(
            "_mensagens.html", {"oob": True}, request=self.request
        )
        return HttpResponse(painel_html + mensagens_html)

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


class ComprovanteDownloadView(LoginRequiredMixin, View):
    """Baixa autenticada do comprovante de um pagamento (nunca por URL pública)."""

    def get(self, request, pk):
        pagamento = get_object_or_404(Pagamento, pk=pk)
        return servir_anexo(pagamento.comprovante)
