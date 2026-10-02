from io import BytesIO
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.paginacao import paginar
from apps.usuarios.mixins import DonoRequeridoMixin

from .forms import PeriodoForm
from .pdf import montar_pdf
from .servicos import montar_hoje, montar_juros_em_aberto, montar_painel_inicial, montar_relatorio

POR_PAGINA_JUROS = 20

# Excel/Sheets interpretam célula que começa com um destes como fórmula.
_GATILHOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _celula(valor):
    """Neutraliza injeção de fórmula: prefixa `'` em texto que abre com = + - @."""
    if isinstance(valor, str) and valor[:1] in _GATILHOS_FORMULA:
        return "'" + valor
    return valor


def _contexto(request):
    dados = request.GET or {
        "periodo": "diario",
        "referencia": timezone.localdate().isoformat(),
    }
    form = PeriodoForm(dados)
    if not form.is_valid():
        return {"form": form, "relatorio": None, "querystring": "", "inicio_iso": "", "fim_iso": ""}
    relatorio = montar_relatorio(form.cleaned_data["inicio"], form.cleaned_data["fim"])
    querystring = urlencode(
        {
            "periodo": form.cleaned_data["periodo"],
            "referencia": form.cleaned_data["referencia"].isoformat(),
            "inicio": form.cleaned_data["inicio"].isoformat(),
            "fim": form.cleaned_data["fim"].isoformat(),
        }
    )
    return {
        "form": form,
        "relatorio": relatorio,
        "querystring": querystring,
        "inicio_iso": form.cleaned_data["inicio"].isoformat(),
        "fim_iso": form.cleaned_data["fim"].isoformat(),
    }


class InicioView(LoginRequiredMixin, TemplateView):
    """Tela inicial: o que pede ação hoje, a fila de cobrança, números-chave e gráficos.

    Aberta a qualquer usuário autenticado (a Yslane também usa). Os dados vêm
    de ``montar_painel_inicial``; os gráficos recebem listas já convertidas
    para ``float``/``int`` e são injetados no HTML via ``json_script``.
    """

    template_name = "relatorios/inicio.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.pagamentos.badge import status_whatsapp

        painel = montar_painel_inicial()
        ctx["painel"] = painel
        ctx["hoje"] = montar_hoje(painel["hoje"])
        ctx["whatsapp_estado"] = status_whatsapp()
        ctx["serie_json"] = {
            "labels": [m["rotulo"] for m in painel["serie_meses"]],
            "recebido": [float(m["recebido"]) for m in painel["serie_meses"]],
            "previsto": [float(m["previsto"]) for m in painel["serie_meses"]],
        }
        contagem = painel["status_contagem"]
        ctx["status_json"] = {
            "labels": ["Em dia", "Atrasado", "Inadimplente", "Quitado"],
            "data": [
                contagem.get("em_dia", 0),
                contagem.get("atrasado", 0),
                contagem.get("inadimplente", 0),
                contagem.get("quitado", 0),
            ],
        }
        return ctx


class RelatorioView(DonoRequeridoMixin, TemplateView):
    template_name = "relatorios/painel.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **_contexto(self.request)}


class JurosView(DonoRequeridoMixin, TemplateView):
    """Juros: em aberto hoje (por contrato atrasado) e recebidos no período."""

    template_name = "relatorios/juros.html"

    def get_context_data(self, **kwargs):
        ctx = {**super().get_context_data(**kwargs), **_contexto(self.request)}
        juros_em_aberto = montar_juros_em_aberto()
        pagina = paginar(self.request, juros_em_aberto["linhas"], POR_PAGINA_JUROS)
        juros_em_aberto["total_linhas"] = len(juros_em_aberto["linhas"])
        juros_em_aberto["linhas"] = list(pagina["page_obj"].object_list)
        ctx["juros_em_aberto"] = juros_em_aberto
        ctx.update(pagina)
        relatorio = ctx["relatorio"]
        ctx["juros_recebimentos"] = (
            [p for p in relatorio["recebimentos"] if p.juros_pago] if relatorio else []
        )
        return ctx


class RelatorioExcelView(DonoRequeridoMixin, View):
    def get(self, request):
        ctx = _contexto(request)
        if ctx["relatorio"] is None:
            return HttpResponse("Período inválido.", status=400)
        rel = ctx["relatorio"]
        wb = Workbook()
        resumo = wb.active
        resumo.title = "Resumo"
        resumo.append(["Relatório de pagamentos"])
        resumo.append(["Período", rel["inicio"], rel["fim"]])
        resumo.append([])
        resumo.append(["Indicador", "Valor"])
        indicadores = [
            ("Total previsto", rel["total_previsto"]),
            ("Total recebido", rel["total_recebido"]),
            ("Total em atraso", rel["total_atrasado"]),
            ("Pagamentos registrados", rel["quantidade_recebimentos"]),
            ("Parcelas em atraso", rel["quantidade_atrasados"]),
            ("Novos clientes", rel["novos_clientes"]),
            ("Contratos quitados", rel["contratos_quitados"]),
        ]
        for item in indicadores:
            resumo.append(item)

        recebidos = wb.create_sheet("Recebimentos")
        recebidos.append(["Data", "Cliente", "Contrato", "Parcela", "Forma", "Valor"])
        for pagamento in rel["recebimentos"]:
            recebidos.append([
                pagamento.data_pagamento,
                _celula(pagamento.contrato.cliente.nome),
                _celula(pagamento.contrato.apelido),
                pagamento.vencimento.numero if pagamento.vencimento else "",
                pagamento.get_forma_display(),
                pagamento.valor_pago,
            ])

        atrasados = wb.create_sheet("Em atraso")
        atrasados.append(
            ["Vencimento", "Cliente", "Contrato", "Parcela", "Previsto", "Pago", "Em aberto"]
        )
        for vencimento in rel["atrasados"]:
            atrasados.append([
                vencimento.data_vencimento,
                _celula(vencimento.contrato.cliente.nome),
                _celula(vencimento.contrato.apelido),
                vencimento.numero,
                vencimento.valor_previsto,
                vencimento.valor_pago,
                vencimento.valor_em_aberto,
            ])

        for planilha in wb.worksheets:
            planilha.freeze_panes = "A2"
            for cell in planilha[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1E6E5A")
                cell.alignment = Alignment(vertical="center")
            for coluna in planilha.columns:
                largura = min(max(len(str(c.value or "")) for c in coluna) + 2, 40)
                planilha.column_dimensions[get_column_letter(coluna[0].column)].width = largura

        for row in resumo.iter_rows(min_row=5, max_row=7, min_col=2, max_col=2):
            row[0].number_format = 'R$ #,##0.00'
        for planilha in (recebidos, atrasados):
            for row in planilha.iter_rows(min_row=2):
                row[0].number_format = "dd/mm/yyyy"
        for row in recebidos.iter_rows(min_row=2, min_col=6, max_col=6):
            row[0].number_format = 'R$ #,##0.00'
        for row in atrasados.iter_rows(min_row=2, min_col=5, max_col=7):
            for cell in row:
                cell.number_format = 'R$ #,##0.00'

        arquivo = BytesIO()
        wb.save(arquivo)
        nome = f"relatorio-{rel['inicio']:%Y-%m-%d}-a-{rel['fim']:%Y-%m-%d}.xlsx"
        resposta = HttpResponse(
            arquivo.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        return resposta


class RelatorioPDFView(DonoRequeridoMixin, View):
    def get(self, request):
        ctx = _contexto(request)
        if ctx["relatorio"] is None:
            return HttpResponse("Período inválido.", status=400)
        rel = ctx["relatorio"]
        arquivo = BytesIO()
        montar_pdf(arquivo, rel, gerado_por=request.user.get_full_name() or request.user.get_username())
        nome = f"relatorio-{rel['inicio']:%Y-%m-%d}-a-{rel['fim']:%Y-%m-%d}.pdf"
        resposta = HttpResponse(arquivo.getvalue(), content_type="application/pdf")
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        return resposta
