"""Painel "Cobrar hoje" (Fase 2 — Modalidade A, base da v1).

A lista de contratos a cobrar no dia mora em `apps.pagamentos.agenda` (usada
também pelo lembrete diário — `apps.pagamentos.lembrete`). O disparo do
lembrete no WhatsApp da Yslane às 08:30 já tem o texto e o job prontos; falta
só a conta WhatsApp Business para o envio de verdade (ver `lembrete.py`).
"""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView
from django.utils import timezone

from apps.arquivos import servir_anexo
from apps.paginacao import paginar
from apps.contratos.models import Contrato

from . import cora_api
from .agenda import montar_agenda_do_dia
from .contatos import promessas_a_retornar
from .proximas import JANELAS, proximas_cobrancas
from . import acordos, parcelas, recebidos
from .forms import AcordoNovaDataForm, AcordoPerdaoForm, ContatoDeCobrancaForm, PagamentoForm, ParcelaEditarForm
from .comprovantes import conferir_na_cora
from .limpeza import encerrar_cobranca_automatica
from .models import (
    CobrancaCora,
    ComprovanteRecebido,
    ConfiguracaoCobranca,
    Pagamento,
    QrWhatsApp,
    Vencimento,
)
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
        ctx["estrutura_opcoes"] = Contrato.ESTRUTURAS_ATIVAS
        ctx["config_cobranca"] = ConfiguracaoCobranca.obter()
        ctx["promessas"] = promessas_a_retornar(ctx["hoje"])
        if ctx["promessas"]:
            n = len(ctx["promessas"])
            messages.warning(
                self.request,
                f"{n} promessa{'s' if n != 1 else ''} de pagamento para hoje ou vencida{'s' if n != 1 else ''}: "
                "vale falar com o cliente de novo.",
            )
        return ctx


class AcordoView(LoginRequiredMixin, View):
    """Negocia uma parcela atrasada: perdoar juros ou marcar uma nova data (GET mostra, POST aplica)."""

    template_name = "pagamentos/acordo.html"

    def _contexto(self, vencimento, **extra):
        hoje = timezone.localdate()
        contrato = vencimento.contrato
        dias = acordos.atraso.dias_de_atraso(vencimento.data_vencimento, hoje, contrato.estrutura)
        juros = acordos.juros_a_cobrar(vencimento, hoje)
        return {
            "vencimento": vencimento, "contrato": contrato, "hoje": hoje, "dias_atraso": dias,
            "juros_hoje": juros, "total_hoje": max(vencimento.saldo, 0) + juros,
            "motivo": acordos.motivo_para_nao_negociar(vencimento),
            "juros_perdoados": vencimento.juros_abonado,
            **extra,
        }

    def _vencimento(self, pk):
        return get_object_or_404(Vencimento.objects.select_related("contrato__cliente"), pk=pk)

    def get(self, request, pk):
        vencimento = self._vencimento(pk)
        ctx = self._contexto(vencimento)
        ctx["form_perdao"] = AcordoPerdaoForm(initial={"juros": f"{ctx['juros_hoje']:.2f}".replace(".", ",")})
        ctx["form_data"] = AcordoNovaDataForm()
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        vencimento = self._vencimento(pk)
        tipo = request.POST.get("tipo")
        usa_data = tipo == "nova_data"
        form = (AcordoNovaDataForm if usa_data else AcordoPerdaoForm)(request.POST)
        if form.is_valid():
            try:
                acordo, avisos = acordos.aplicar_acordo(
                    vencimento, tipo=tipo, autor=request.user, nota=form.cleaned_data.get("nota", ""),
                    nova_data=form.cleaned_data.get("nova_data"), juros_perdoar=form.cleaned_data.get("juros"),
                )
            except acordos.AcordoInvalido as exc:
                form.add_error(None, str(exc))
            else:
                if usa_data:
                    messages.success(
                        request,
                        f"Acordo registrado: parcela {vencimento.numero} agora é cobrada em {acordo.nova_data:%d/%m/%Y}.",
                    )
                else:
                    messages.success(
                        request,
                        f"Acordo registrado: R$ {acordo.juros_perdoados:.2f} de juros perdoados na parcela {vencimento.numero}."
                        .replace(".", ","),
                    )
                for nivel, texto in avisos:
                    getattr(messages, nivel)(request, texto)
                return redirect(reverse("contratos:detalhe", args=[vencimento.contrato_id]) + "#acordos")
        ctx = self._contexto(vencimento)
        hoje_juros = f"{ctx['juros_hoje']:.2f}".replace(".", ",")
        ctx["form_perdao"] = form if not usa_data else AcordoPerdaoForm(initial={"juros": hoje_juros})
        ctx["form_data"] = form if usa_data else AcordoNovaDataForm()
        return render(request, self.template_name, ctx)


class ParcelaEditarView(LoginRequiredMixin, View):
    """Edita data, valor e valor a mais de uma parcela (GET mostra, POST aplica)."""

    template_name = "pagamentos/parcela_editar.html"

    def _vencimento(self, pk):
        return get_object_or_404(Vencimento.objects.select_related("contrato__cliente"), pk=pk)

    def _render(self, request, vencimento, form):
        return render(request, self.template_name, {
            "vencimento": vencimento, "contrato": vencimento.contrato, "form": form,
            "motivo": parcelas.motivo_para_nao_editar(vencimento),
        })

    def get(self, request, pk):
        vencimento = self._vencimento(pk)
        form = ParcelaEditarForm(initial={
            "data_vencimento": vencimento.data_vencimento,
            "valor_base": f"{parcelas.valor_base(vencimento):.2f}".replace(".", ","),
            "acrescimo": f"{vencimento.acrescimo:.2f}".replace(".", ",") if vencimento.acrescimo else "",
            "motivo": vencimento.acrescimo_motivo,
        })
        return self._render(request, vencimento, form)

    def post(self, request, pk):
        vencimento = self._vencimento(pk)
        form = ParcelaEditarForm(request.POST)
        if form.is_valid():
            try:
                avisos = parcelas.editar_parcela(
                    vencimento, data_vencimento=form.cleaned_data["data_vencimento"],
                    valor_base=form.cleaned_data["valor_base"], acrescimo=form.cleaned_data["acrescimo"],
                    motivo=form.cleaned_data["motivo"], autor=request.user,
                )
            except parcelas.ParcelaInvalida as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f"Parcela {vencimento.numero} atualizada.")
                for nivel, texto in avisos:
                    getattr(messages, nivel)(request, texto)
                return redirect(reverse("contratos:detalhe", args=[vencimento.contrato_id]))
        return self._render(request, vencimento, form)


class AcordoDesfazerView(LoginRequiredMixin, View):
    """Desfaz um acordo enquanto a parcela não foi paga (POST)."""

    def post(self, request, pk):
        from .models import Acordo

        acordo = get_object_or_404(Acordo.objects.select_related("contrato"), pk=pk)
        try:
            avisos = acordos.desfazer_acordo(acordo, autor=request.user)
        except acordos.AcordoInvalido as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Acordo desfeito: a parcela voltou ao que era antes.")
            for nivel, texto in avisos:
                getattr(messages, nivel)(request, texto)
        return redirect(reverse("contratos:detalhe", args=[acordo.contrato_id]) + "#acordos")


class ContatoCriarView(LoginRequiredMixin, View):
    """Anota um contato de cobrança no contrato (POST)."""

    def post(self, request, contrato_pk):
        contrato = get_object_or_404(Contrato, pk=contrato_pk)
        form = ContatoDeCobrancaForm(request.POST)
        if form.is_valid():
            contato = form.save(commit=False)
            contato.contrato = contrato
            contato.autor = request.user
            contato.save()
            if contato.promessa_para:
                messages.success(request, f"Promessa registrada: pagamento até {contato.promessa_para:%d/%m/%Y}.")
            else:
                messages.success(request, "Contato registrado.")
        else:
            for erros in form.errors.values():
                for erro in erros:
                    messages.error(request, erro)
        return redirect(reverse("contratos:detalhe", args=[contrato.pk]) + "#contatos")


class ContatoExcluirView(LoginRequiredMixin, View):
    """Apaga uma anotação registrada por engano (POST)."""

    def post(self, request, pk):
        from .models import ContatoDeCobranca

        contato = get_object_or_404(ContatoDeCobranca, pk=pk)
        contrato_pk = contato.contrato_id
        contato.delete()
        messages.success(request, "Anotação apagada.")
        return redirect(reverse("contratos:detalhe", args=[contrato_pk]) + "#contatos")


class ProximasCobrancasView(LoginRequiredMixin, TemplateView):
    """O que será cobrado nos próximos dias (a partir de amanhã), agrupado por data de cobrança."""

    template_name = "pagamentos/proximas_cobrancas.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            dias = int(self.request.GET.get("dias", 14))
        except ValueError:
            dias = 14
        dias = dias if dias in JANELAS else 14
        ctx.update(proximas_cobrancas(dias), janelas=JANELAS, hoje=timezone.localdate())
        ctx["config_cobranca"] = ConfiguracaoCobranca.obter()
        return ctx


class RecebidosView(LoginRequiredMixin, TemplateView):
    """Pix recebidos direto na Cora (transferência comum) que ainda não viraram baixa no sistema."""

    template_name = "pagamentos/recebidos.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        erro = recebidos.sincronizar(forcar=bool(self.request.GET.get("atualizar")))
        ctx.update(recebidos.painel(), erro_cora=erro)
        if ctx["a_registrar"]:
            n = len(ctx["a_registrar"])
            messages.warning(
                self.request,
                f"{n} Pix recebido{'s' if n != 1 else ''} na Cora ainda sem pagamento registrado.",
            )
        return ctx


class RecebidoIgnorarView(LoginRequiredMixin, View):
    """Marca uma entrada do extrato como "não é pagamento de parcela" (POST)."""

    def post(self, request, pk):
        if recebidos.ignorar(pk, request.user):
            messages.success(request, "Entrada ignorada.")
        return redirect("pagamentos:recebidos")


class CobrancasPausaView(LoginRequiredMixin, View):
    """Começa, pausa ou retoma as cobranças automáticas de todo o sistema (POST).

    A primeira vez ("começar") exige o aceite de que está tudo conferido."""

    def post(self, request):
        acao = request.POST.get("acao")
        config = ConfiguracaoCobranca.obter()
        if acao == "pausar":
            ConfiguracaoCobranca.definir(True, request.user)
            messages.warning(
                request,
                "Cobranças automáticas pausadas. Nenhuma mensagem nem Pix será enviado aos clientes até você retomar.",
            )
        elif acao in ("comecar", "retomar"):
            if config.nunca_iniciada and not request.POST.get("conferido"):
                messages.error(request, "Marque que conferiu tudo antes de começar as cobranças. Nada foi alterado.")
            else:
                primeira_vez = config.nunca_iniciada
                ConfiguracaoCobranca.definir(False, request.user)
                messages.success(
                    request,
                    "Cobranças começaram. A próxima rotina cobra os clientes."
                    if primeira_vez
                    else "Cobranças automáticas retomadas. A próxima rotina volta a cobrar normalmente.",
                )
        return _voltar_para_origem(request, padrao="pagamentos:cobrar_hoje")


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
            cancelar_cobranca(cobranca, motivo="Cancelado no painel Pix", autor=request.user)
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


def _voltar_para_origem(request, padrao="pagamentos:pix_painel"):
    """Redireciona para o `next` do formulário — só se for uma página deste site."""
    destino = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        destino = reverse(padrao)
    return redirect(destino)


class PagamentoPrevisaoView(LoginRequiredMixin, View):
    def post(self, request, contrato_pk):
        from .previsao import prever_pagamento

        contrato = get_object_or_404(Contrato, pk=contrato_pk)
        form = PagamentoForm(request.POST, contrato=contrato)
        if contrato.quitado or not form.is_valid() or not form.cleaned_data.get("vencimento"):
            return JsonResponse({"texto": "Confira a parcela, a data e os valores para visualizar o resultado da baixa."})
        dados = form.cleaned_data
        return JsonResponse({"texto": prever_pagamento(
            contrato, dados["vencimento"], dados["valor_pago"], dados["juros_pago"],
        )})


class PagamentoCreateView(LoginRequiredMixin, CreateView):
    """Baixa de um pagamento numa parcela de um contrato.

    Página cheia: as telas abrem o formulário por link e, ao registrar,
    voltam ao contrato.
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["contrato"] = self.contrato
        return kwargs

    def get_initial(self):
        """Veio de "Recebidos na Cora": já traz a data, a forma (Pix) e liga a entrada ao pagamento."""
        initial = super().get_initial()
        from .models import RecebimentoCora

        recebimento = RecebimentoCora.objects.filter(
            pk=self.request.GET.get("recebido") or 0, situacao=RecebimentoCora.Situacao.NOVO
        ).first()
        if recebimento:
            initial["recebido"] = recebimento.pk
            initial["forma"] = Pagamento.Forma.PIX
            initial["data_pagamento"] = timezone.localtime(recebimento.recebido_em).date()
            initial["valor_pago"] = f"{recebimento.valor:.2f}".replace(".", ",")
            initial["juros_pago"] = "0,00"
            self.recebimento_cora = recebimento
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["recebimento_cora"] = getattr(self, "recebimento_cora", None)
        ctx["contrato"] = self.contrato
        from .agenda import resumo_cobranca
        ctx["resumo_cobranca"] = resumo_cobranca(self.contrato)
        ctx["parcelas_abertas"] = self.contrato.vencimentos.exclude(
            status=Vencimento.Status.PAGO
        ).order_by("numero")
        # Pode haver parcela "em aberto" pra mostrar (parcial) sem nenhuma
        # selecionável no formulário — todas já com baixa, saldo ainda não
        # repassado pra próxima (ver Contrato.parcela_em_aberto). Distingue
        # esse caso de "não há mais nada a cobrar" no template.
        ctx["pode_registrar"] = ctx["form"].fields["vencimento"].queryset.exists()
        ctx["juros_ate_hoje"] = ctx["resumo_cobranca"]["juros"]
        return ctx

    def form_valid(self, form):
        pagamento = form.save(commit=False)
        pagamento.contrato = self.contrato
        pagamento.usuario_baixa = self.request.user
        pagamento.registrar()
        self.object = pagamento
        recebidos.vincular(form.cleaned_data.get("recebido"), pagamento, self.request.user)
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

        destino = reverse("contratos:detalhe", args=[self.contrato.pk])
        if venc is not None:
            destino += f"?pago={venc.numero}"
        return redirect(destino)

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


CHAVE_SESSAO_QR_ATIVO = "conexoes_whatsapp_gerar_qr"
QR_RENOVA_SEGUNDOS = 25
#: Quanto tempo, depois do clique em "Gerar QR Code", a página continua renovando o QR sozinha.
#: Passado isso, abrir Conexões não pede QR à Evolution (só um novo clique).
QR_PEDIDO_VALE_SEGUNDOS = 120


def _agora():
    return timezone.now()


def _qr_pedido_ativo(sessao) -> bool:
    """O usuário clicou em "Gerar QR Code" há pouco tempo?

    A sessão guarda o instante do clique. Antes ela guardava só ``True``, que ficava ligado
    para sempre: toda visita à página pedia um QR à Evolution (devagar) sem ninguém ter clicado.
    Esse valor antigo, sem horário, não vale mais.
    """
    pedido = sessao.get(CHAVE_SESSAO_QR_ATIVO)
    if isinstance(pedido, bool) or not isinstance(pedido, (int, float)):
        return False
    return 0 <= _agora().timestamp() - pedido < QR_PEDIDO_VALE_SEGUNDOS


def _qr_guardado_valido():
    """``(QrWhatsApp, segundos_decorridos)`` do QR ainda válido, ou ``(None, 0)``."""
    guardado = QrWhatsApp.atual()
    if guardado:
        decorrido = (_agora() - guardado.gerado_em).total_seconds()
        if 0 <= decorrido < QR_RENOVA_SEGUNDOS:
            return guardado, decorrido
    return None, 0.0


class ConexoesView(LoginRequiredMixin, TemplateView):
    """Status das integrações (WhatsApp, Cora) e QR code pra reconectar o WhatsApp.

    Abrir a página é rápido: o estado do WhatsApp vem da cache curta e **nenhum QR é pedido
    aqui**. O QR só nasce depois do clique em "Gerar QR Code" e é gerado em segundo plano
    (``ConexoesQrView``): a tela mostra "Gerando…" e se atualiza quando ele fica pronto.

    O QR e a hora em que foi gerado ficam no banco (`QrWhatsApp`, um só para a
    instância da Evolution — é lá que ele expira): ao fechar a página, sair e
    entrar de novo ou abrir em outro aparelho antes de expirar, a tela mostra o
    mesmo código com o cronômetro de onde parou — em vez de reiniciar a contagem
    e deixar ler um código já expirado.
    """

    template_name = "pagamentos/conexoes.html"

    def get_context_data(self, **kwargs):
        from django.conf import settings

        from .badge import TTL_WHATSAPP_SEGUNDOS, status_whatsapp_ao_vivo
        from .models import EventoCora

        ctx = super().get_context_data(**kwargs)
        status_whatsapp = status_whatsapp_ao_vivo()
        erro_whatsapp = "Não foi possível consultar o WhatsApp agora." if status_whatsapp == "erro" else ""

        sessao = self.request.session
        if status_whatsapp in ("open", "simulado"):
            sessao.pop(CHAVE_SESSAO_QR_ATIVO, None)
            QrWhatsApp.limpar()

        qr_code = ""
        qr_decorrido = 0.0
        quer_qr = status_whatsapp not in ("open", "simulado") and _qr_pedido_ativo(sessao)
        if quer_qr:
            guardado, qr_decorrido = _qr_guardado_valido()
            qr_code = guardado.imagem if guardado else ""

        ctx.update(
            status_whatsapp=status_whatsapp,
            erro_whatsapp=erro_whatsapp,
            qr_code=qr_code,
            quer_qr=bool(quer_qr),
            gerando_qr=bool(quer_qr and not qr_code),
            qr_renova_segundos=QR_RENOVA_SEGUNDOS,
            qr_restante_segundos=max(1, round(QR_RENOVA_SEGUNDOS - qr_decorrido)),
            # Ponto decimal fixo: vai direto para o CSS (animation-delay negativo).
            qr_atraso_css=f"-{qr_decorrido:.1f}s",
            ttl_status_whatsapp=TTL_WHATSAPP_SEGUNDOS,
            cora_provider=settings.CORA_PROVIDER,
            cora_webhook_configurado=bool(settings.CORA_WEBHOOK_TOKEN),
            ultimo_evento_cora=EventoCora.objects.order_by("-recebido_em").first(),
        )
        return ctx


class ConexoesStatusView(LoginRequiredMixin, View):
    """Estado atual do WhatsApp em JSON, pra tela se atualizar sozinha (polling)."""

    def get(self, request):
        from .badge import status_whatsapp_ao_vivo

        response = JsonResponse({"estado": status_whatsapp_ao_vivo()})
        response["Cache-Control"] = "no-store"
        return response


class ConexoesGerarQrView(LoginRequiredMixin, View):
    """Registra o pedido de QR code (vale por alguns minutos) e volta para a tela, sem esperar a Evolution."""

    def post(self, request):
        cache.delete("whatsapp_status")  # a página e o menu já refletem na hora
        request.session[CHAVE_SESSAO_QR_ATIVO] = _agora().timestamp()
        QrWhatsApp.limpar()  # "gerar outro" = código novo de verdade
        return redirect("pagamentos:conexoes")


class ConexoesQrView(LoginRequiredMixin, View):
    """Gera o QR code em segundo plano (a tela chama este endereço depois de abrir).

    É aqui que se espera pela Evolution, que pode levar alguns segundos: a página já abriu e
    mostra "Gerando o QR code…". Só atende quem pediu o QR há pouco, e reaproveita o QR ainda válido.
    """

    def post(self, request):
        from .badge import status_whatsapp_ao_vivo
        from .whatsapp import WhatsAppErro, obter_qrcode

        resposta = JsonResponse({"ok": False, "erro": "Clique em “Gerar QR Code” para pedir um código."}, status=409)
        if not _qr_pedido_ativo(request.session):
            return resposta
        if status_whatsapp_ao_vivo() in ("open", "simulado"):
            return JsonResponse({"ok": True, "conectado": True})
        guardado, _ = _qr_guardado_valido()
        if guardado:
            return JsonResponse({"ok": True})
        try:
            QrWhatsApp.guardar(obter_qrcode(), _agora())
        except WhatsAppErro as exc:
            return JsonResponse({"ok": False, "erro": str(exc)})
        return JsonResponse({"ok": True})


class ComprovanteDownloadView(LoginRequiredMixin, View):
    """Baixa autenticada do comprovante de um pagamento (nunca por URL pública)."""

    def get(self, request, pk):
        pagamento = get_object_or_404(Pagamento, pk=pk)
        return servir_anexo(pagamento.comprovante)
