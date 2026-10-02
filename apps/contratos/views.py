import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.arquivos import servir_anexo
from apps.clientes.models import Cliente

from .forms import ContratoForm, DocumentoContratoForm, PlanilhaPreviaForm, PrevisaoContratoForm, ResolverImportacaoForm, moeda_para_decimal
from .models import Contrato, DocumentoContrato, ImportacaoContratoPendente


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


def _gerar_parcelas_ao_salvar(request, contrato):
    """Gera/atualiza os `Vencimento` logo ao salvar o contrato pela web.

    Faz o mesmo que o botão "Gerar parcelas" e o job diário fazem por contrato
    (idempotente): cria as parcelas que faltam até ~60 dias à frente, recalcula
    a data prevista de quitação e sincroniza o status. Sem `valor_parcela` não
    há o que gerar — nesse caso o aviso do formulário já orienta o usuário e o
    botão na tela de detalhe continua disponível para depois.
    """
    if contrato.quitado or contrato.valor_parcela is None:
        return
    novos = contrato.gerar_vencimentos()
    removidas = contrato.podar_vencimentos_excedentes()
    contrato.atualizar_data_prevista_quitacao()
    contrato.sincronizar_status()
    if novos:
        messages.info(request, f"{len(novos)} parcela(s) gerada(s) automaticamente.")
    if removidas:
        messages.info(
            request,
            f"Nº de parcelas reduzido: {len(removidas)} parcela(s) além do novo "
            f"total ({contrato.num_parcelas}) foram removidas automaticamente.",
        )
    elif removidas is None:
        messages.warning(
            request,
            "O nº de parcelas foi reduzido, mas há parcela além dele com pagamento "
            "ou Pix já gerado — nada foi apagado. Revise as parcelas na mão.",
        )


LIMITE_PARCELAS_NO_CONTRATO = 24
LIMITE_PAGAMENTOS_NO_CONTRATO = 30


def _parcelas_relevantes(vencimentos, *, todas=False):
    """Parcelas mostradas na tela do contrato.

    Contrato longo: em vez das 24 primeiras (que escondiam as parcelas atuais
    depois do dia 24), mostra uma janela que começa um pouco antes da primeira
    parcela ainda não paga — o que a Yslane precisa ver para cobrar.
    """
    if todas or len(vencimentos) <= LIMITE_PARCELAS_NO_CONTRATO:
        return vencimentos
    primeira_aberta = next(
        (i for i, v in enumerate(vencimentos) if v.status != v.Status.PAGO),
        len(vencimentos) - 1,
    )
    inicio = min(
        max(0, primeira_aberta - 3), len(vencimentos) - LIMITE_PARCELAS_NO_CONTRATO
    )
    return vencimentos[inicio : inicio + LIMITE_PARCELAS_NO_CONTRATO]


class ContratoPrevisaoView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.pagamentos.previsao import moeda
        from apps.pagamentos.recorrencia import data_da_parcela

        form = PrevisaoContratoForm(request.POST)
        if not form.is_valid():
            return JsonResponse({"texto": "Informe valores positivos, a frequência e a data de início para visualizar o plano."})
        contrato = Contrato(**form.cleaned_data)
        contrato.calcular_num_parcelas(salvar=False)
        try:
            primeira = data_da_parcela(contrato.data_inicio, contrato.estrutura, 1)
            ultima = data_da_parcela(contrato.data_inicio, contrato.estrutura, contrato.num_parcelas)
        except (ValueError, OverflowError):
            return JsonResponse({"texto": "Confira a data e a quantidade de parcelas: o período informado é muito longo."})
        texto = (
            f"{contrato.num_parcelas} parcelas de {moeda(contrato.valor_parcela)} · {contrato.get_estrutura_display()}.\n"
            f"Primeiro vencimento: {primeira:%d/%m/%Y}. Último: {ultima:%d/%m/%Y}.\n"
            f"Total das parcelas: {moeda(contrato.total_das_parcelas)}. Valor do contrato: {moeda(contrato.valor_total)}."
        )
        if not contrato.parcelas_conferem:
            texto += "\nAtenção: os totais são diferentes. Ajuste os valores ou a quantidade; a última parcela não é reduzida automaticamente."
        return JsonResponse({"texto": texto})


class PlanilhaPreviaView(LoginRequiredMixin, View):
    template_name = "contratos/importar_previa.html"

    def get(self, request):
        return self._resposta(request, PlanilhaPreviaForm())

    def post(self, request):
        form = PlanilhaPreviaForm(request.POST, request.FILES)
        linhas = avisos = None
        if form.is_valid():
            from .importacao import analisar
            try:
                linhas, avisos = analisar(form.cleaned_data["arquivo"])
            except Exception:
                form.add_error("arquivo", "Não foi possível ler a planilha. Confira o arquivo e o cabeçalho.")
            else:
                request.session["previsao_importacao"] = [
                    {**linha, "inicio": linha.get("inicio").isoformat() if linha.get("inicio") else None,
                     "vencimento": linha.get("vencimento").isoformat() if linha.get("vencimento") else None,
                     "valor": str(linha["valor"]) if linha.get("valor") is not None else None,
                     "juros": str(linha["juros"]) if linha.get("juros") is not None else None}
                    for linha in linhas
                ]
        return self._resposta(request, form, linhas, avisos)

    def _resposta(self, request, form, linhas=None, avisos=None):
        resumo = None
        if linhas is not None:
            from .importacao import contar_por_cliente

            clientes, validas = contar_por_cliente(linhas)
            resumo = {
                "total": len(linhas),
                "clientes": clientes,
                "contratos_extras": validas - clientes,
                "com_erro": sum(bool(linha.get("erros")) for linha in linhas),
                "revisao": sum(not linha.get("erros") and bool(linha.get("alertas")) for linha in linhas),
            }
        return render(request, self.template_name, {"form": form, "linhas": linhas, "avisos": avisos, "resumo": resumo})


class ImportarPendenciasView(LoginRequiredMixin, View):
    def post(self, request):
        linhas = request.session.pop("previsao_importacao", [])
        criadas = 0
        for linha in linhas:
            if linha.get("erros"):
                continue
            problemas = linha.get("alertas", [])
            ImportacaoContratoPendente.objects.create(
                dados=linha, problemas=problemas, linha_origem=linha["linha"]
            )
            criadas += 1
        messages.success(request, f"{criadas} linha(s) enviada(s) para revisão. Nenhum contrato foi criado ainda.")
        return redirect("contratos:importacao_pendencias")


class ImportacaoPendenciasView(LoginRequiredMixin, ListView):
    model = ImportacaoContratoPendente
    template_name = "contratos/importacao_pendencias.html"
    context_object_name = "pendencias"

    def get_queryset(self):
        return super().get_queryset().filter(resolvida_em__isnull=True)


class ResolverImportacaoView(LoginRequiredMixin, View):
    template_name = "contratos/resolver_importacao.html"

    def dispatch(self, request, *args, **kwargs):
        self.pendencia = get_object_or_404(ImportacaoContratoPendente, pk=kwargs["pk"], resolvida_em__isnull=True)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        dados = self.pendencia.dados
        return render(request, self.template_name, {"pendencia": self.pendencia, "form": ResolverImportacaoForm(initial={"cpf": dados.get("cpf", ""), "telefone": dados.get("telefone", ""), "parcelas_ja_pagas": 0})})

    def post(self, request, pk):
        form = ResolverImportacaoForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"pendencia": self.pendencia, "form": form})
        dados = self.pendencia.dados
        try:
            with transaction.atomic():
                cliente = Cliente.objects.filter(cpf=form.cleaned_data["cpf"]).first()
                if cliente and cliente.nome != dados["cliente"]:
                    raise ValueError("Já existe outro cliente com este CPF.")
                if cliente is None:
                    cliente = Cliente(nome=dados["cliente"], cpf=form.cleaned_data["cpf"], telefone_whatsapp=form.cleaned_data["telefone"])
                    cliente.full_clean()
                    cliente.save()
                total = moeda_para_decimal(form.cleaned_data["valor_total"])
                if total is None or total <= 0:
                    raise ValueError("Informe o valor total financiado.")
                pagas = form.cleaned_data.get("parcelas_ja_pagas") or 0
                if pagas > int(dados["parcelas"]):
                    raise ValueError("Parcelas já pagas não pode ser maior que o total.")
                contrato = Contrato.objects.create(cliente=cliente, apelido=dados["modelo"], aparelho_modelo=dados["modelo"], valor_total=total, valor_parcela=moeda_para_decimal(dados["valor"]), juros_diario=moeda_para_decimal(dados["juros"]), num_parcelas=int(dados["parcelas"]), estrutura=dados["estrutura"], data_inicio=datetime.date.fromisoformat(dados["inicio"]), proximo_vencimento=datetime.date.fromisoformat(dados["vencimento"]), observacoes=dados.get("observacoes", ""))
                _gerar_parcelas_ao_salvar(request, contrato)
                _registrar_parcelas_ja_pagas(request, contrato, pagas)
                self.pendencia.resolvida_em = timezone.now()
                self.pendencia.save(update_fields=["resolvida_em"])
        except (ValueError, ValidationError) as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"pendencia": self.pendencia, "form": form})
        messages.success(request, f"Contrato de {cliente.nome} criado e liberado para cobrança automática.")
        return redirect("contratos:detalhe", pk=contrato.pk)


class ContratoListView(LoginRequiredMixin, ListView):
    model = Contrato
    template_name = "contratos/lista.html"
    context_object_name = "contratos"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente").order_by("cliente__nome", "apelido")
        self.estrutura = self.request.GET.get("estrutura", "").strip()
        if self.estrutura:
            qs = qs.filter(estrutura=self.estrutura)
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
        ctx["estrutura_atual"] = self.estrutura
        ctx["estrutura_opcoes"] = Contrato.Estrutura.choices
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
        from apps.pagamentos.agenda import resumo_cobranca
        ctx["resumo_cobranca"] = resumo_cobranca(contrato)
        # Entrada: Pagamento sem parcela vinculada (ver _registrar_entrada) —
        # já veio no prefetch de "pagamentos", sem consulta extra.
        ctx["entradas"] = [p for p in contrato.pagamentos.all() if p.vencimento_id is None]
        vencimentos = list(contrato.vencimentos.all())
        pagas = sum(1 for v in vencimentos if v.status == v.Status.PAGO)
        ctx["pode_quitar"] = (
            not contrato.quitado
            and bool(contrato.num_parcelas)
            and pagas >= contrato.num_parcelas
        )
        ver_todas = self.request.GET.get("todas") == "1"
        ctx["ver_todas"] = ver_todas
        ctx["total_venc"] = len(vencimentos)
        ctx["vencimentos_exibidos"] = _parcelas_relevantes(vencimentos, todas=ver_todas)
        pagamentos = list(contrato.pagamentos.all())
        ctx["total_pagamentos"] = len(pagamentos)
        ctx["pagamentos_exibidos"] = (
            pagamentos if ver_todas else pagamentos[:LIMITE_PAGAMENTOS_NO_CONTRATO]
        )
        return ctx


def _registrar_parcelas_ja_pagas(request, contrato, quantidade):
    """Marca como pagas as primeiras ``quantidade`` parcelas, para um contrato
    que já estava em andamento antes de entrar no sistema.

    Usa a própria data de vencimento como data do pagamento (não temos a data
    real) e o valor previsto como valor pago — se algum desses detalhes
    estiver errado, dá para estornar e refazer pela tela do contrato depois.
    Parcela que já tem baixa (não deveria acontecer num contrato recém-criado)
    é pulada, não duplicada.
    """
    if not quantidade:
        return
    from apps.pagamentos.models import Pagamento, Vencimento

    pendentes = (
        contrato.vencimentos.filter(numero__lte=quantidade)
        .exclude(status=Vencimento.Status.PAGO)
        .order_by("numero")
    )
    registradas = 0
    for venc in pendentes:
        Pagamento(
            contrato=contrato,
            vencimento=venc,
            data_pagamento=venc.data_vencimento,
            valor_pago=venc.valor_previsto,
            forma=Pagamento.Forma.OUTRO,
            usuario_baixa=request.user if request.user.is_authenticated else None,
            observacao="Pagamento anterior ao cadastro no sistema (registrado na migração).",
        ).registrar()
        registradas += 1
    if registradas:
        messages.success(
            request, f"{registradas} parcela(s) anterior(es) marcada(s) como paga(s)."
        )
    faltam = quantidade - registradas
    if faltam > 0:
        messages.warning(
            request,
            f"Só {registradas} parcela(s) estavam geradas até agora — as outras "
            f"{faltam} não foram marcadas. Gere mais parcelas e registre-as pela "
            "tela do contrato, se for o caso.",
        )


def _registrar_entrada(request, contrato, valor, forma):
    """Registra a entrada como um `Pagamento` sem parcela vinculada.

    ``Pagamento.vencimento`` é opcional — mesmo mecanismo usado pra um
    registro avulso. A entrada não é uma parcela: não aparece na lista de
    vencimentos, não pode ser confundida com uma baixa de parcela, mas entra
    normalmente nos relatórios e no histórico do cliente/contrato (o `—` na
    coluna "Parcela" é intencional).
    """
    if not valor:
        return
    from apps.pagamentos.models import Pagamento

    Pagamento(
        contrato=contrato,
        vencimento=None,
        data_pagamento=contrato.data_inicio,
        valor_pago=valor,
        forma=forma,
        usuario_baixa=request.user if request.user.is_authenticated else None,
        observacao="Entrada do contrato.",
    ).registrar()
    valor_fmt = f"{valor:.2f}".replace(".", ",")
    messages.success(request, f"Entrada de R$ {valor_fmt} registrada.")


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
        self.object.calcular_num_parcelas()
        _avisar_se_parcela_nao_bate(self.request, self.object)
        _gerar_parcelas_ao_salvar(self.request, self.object)
        quantidade = form.cleaned_data.get("parcelas_ja_pagas") or 0
        if quantidade:
            _registrar_parcelas_ja_pagas(self.request, self.object, quantidade)
        entrada = form.cleaned_data.get("entrada")
        if entrada:
            _registrar_entrada(
                self.request, self.object, entrada, form.cleaned_data.get("entrada_forma")
            )
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
        self.object.calcular_num_parcelas()
        _avisar_se_parcela_nao_bate(self.request, self.object)
        _gerar_parcelas_ao_salvar(self.request, self.object)
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


class ContratoGerarVencimentosView(LoginRequiredMixin, View):
    """Gera os `Vencimento` do contrato pela web (POST).

    Faz o mesmo que o job ``manage.py gerar_vencimentos`` faz por contrato:
    cria as parcelas que faltam até ~60 dias à frente (a partir de
    `data_inicio` + estrutura + `valor_parcela`), recalcula a data prevista de
    quitação e roda `sincronizar_status()`. Enquanto o cron do provedor não
    roda (Fase 2 / deploy), este botão é a forma de gerar parcelas sem abrir o
    terminal. Idempotente — pode ser clicado de novo depois para gerar as
    parcelas seguintes.
    """

    def post(self, request, pk):
        contrato = get_object_or_404(Contrato, pk=pk)
        if contrato.quitado:
            messages.info(request, "Contrato quitado — não há parcelas novas a gerar.")
        elif contrato.valor_parcela is None:
            messages.error(
                request,
                "Informe o valor da parcela no contrato antes de gerar as parcelas.",
            )
        else:
            novos = contrato.gerar_vencimentos()
            contrato.atualizar_data_prevista_quitacao()
            contrato.sincronizar_status()
            if novos:
                messages.success(
                    request, f"{len(novos)} nova(s) parcela(s) gerada(s)."
                )
            else:
                messages.info(
                    request,
                    "Nenhuma parcela nova — as parcelas já cobrem o horizonte de 60 dias.",
                )
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


class DocumentoDownloadView(LoginRequiredMixin, View):
    """Baixa autenticada de um documento anexo (nunca por URL pública)."""

    def get(self, request, pk):
        documento = get_object_or_404(DocumentoContrato, pk=pk)
        return servir_anexo(documento.arquivo)
