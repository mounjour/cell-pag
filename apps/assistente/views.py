"""API do conector do Claude Desktop e a tela onde cada pessoa cria a sua chave de acesso.

A API fala só JSON, autentica por chave (``Authorization: Bearer cp_...``) e registra tudo em ``OperacaoApi``.
Quem autoriza cada gravação é a pessoa, no pedido de permissão do Claude Desktop, antes da chamada chegar aqui.
"""

import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import ferramentas
from .models import AcessoApi, OperacaoApi

logger = logging.getLogger(__name__)

LIMITE_POR_HORA = 300


def _acesso_da_requisicao(request) -> AcessoApi | None:
    cabecalho = request.headers.get("Authorization", "")
    if not cabecalho.lower().startswith("bearer "):
        return None
    return AcessoApi.por_chave(cabecalho[7:].strip())


def _dentro_do_limite(acesso: AcessoApi) -> bool:
    chave = f"assistente_api_{acesso.pk}"
    cache.add(chave, 0, 3600)
    return cache.incr(chave) <= LIMITE_POR_HORA


class _ApiView(View):
    """Base: exige a chave, aplica o limite e marca o último uso."""

    marca_uso = True  # baixar arquivos do instalador não é o Claude Desktop usando o sistema

    def dispatch(self, request, *args, **kwargs):
        acesso = _acesso_da_requisicao(request)
        if acesso is None:
            return JsonResponse({"erro": "Chave de acesso ausente, inválida ou revogada."}, status=401)
        if not _dentro_do_limite(acesso):
            return JsonResponse({"erro": "Muitas chamadas na última hora. Tente de novo daqui a pouco."}, status=429)
        request.acesso = acesso
        if self.marca_uso and request.headers.get("X-Teste") != "1":  # instalador e testes não contam como "Claude Desktop conectado"
            acesso.ultimo_uso = timezone.now()
            acesso.save(update_fields=["ultimo_uso"])
        return super().dispatch(request, *args, **kwargs)


class ArquivoApiView(_ApiView):
    """GET dos dois arquivos que o instalador baixa (só quem tem chave válida)."""

    ARQUIVOS = {"conector.py": "celulares_mcp.py", "instalador.py": "instalar_claude_desktop.py"}
    marca_uso = False

    def get(self, request, arquivo):
        if arquivo not in self.ARQUIVOS:
            return JsonResponse({"erro": "Arquivo desconhecido."}, status=404)
        return HttpResponse((CONECTOR / self.ARQUIVOS[arquivo]).read_bytes(), content_type="text/x-python; charset=utf-8")


class FerramentasApiView(_ApiView):
    """GET: lista as ferramentas (o conector monta o que o Claude vê a partir daqui)."""

    def get(self, request):
        return JsonResponse({"ferramentas": ferramentas.catalogo(), "usuario": request.acesso.usuario.nome_curto})


@method_decorator(csrf_exempt, name="dispatch")
class ExecutarApiView(_ApiView):
    """POST ``{"ferramenta": ..., "parametros": {...}}``: roda a ferramenta e registra a operação."""

    def post(self, request):
        try:
            corpo = json.loads(request.body or b"{}")
            nome, parametros = str(corpo.get("ferramenta", "")), corpo.get("parametros") or {}
            if not isinstance(parametros, dict):
                raise ValueError
        except ValueError:
            return JsonResponse({"erro": "Pedido inválido."}, status=400)
        acesso = request.acesso
        grava = nome in ferramentas.ESCRITA
        try:
            texto, resumo, gravou, referencias = ferramentas.executar_ferramenta(nome, parametros, acesso.usuario)
            ok, status = True, 200
        except ferramentas.ErroFerramenta as exc:
            texto, resumo, gravou, referencias, ok, status = str(exc), "", False, {}, False, 400
        except Exception:  # noqa: BLE001 — um erro numa ferramenta não pode derrubar a API
            logger.exception("Falha na ferramenta %s do Claude Desktop", nome)
            texto, resumo, gravou, referencias, ok, status = "Erro interno ao executar esta ferramenta.", "", False, {}, False, 500
        if grava or not ok:
            OperacaoApi.objects.create(
                acesso=acesso, usuario=acesso.usuario, ferramenta=nome[:40], grava=grava,
                parametros={k: v for k, v in parametros.items()}, resumo=resumo or str(parametros.get("resumo", ""))[:300],
                ok=ok, resultado=texto[:2000], referencias=referencias,
            )
        return JsonResponse({"ok": ok, "resultado" if ok else "erro": texto, "gravou": gravou}, status=status)


CONECTOR = settings.BASE_DIR / "apps" / "assistente" / "conector"


class AcessoDesktopView(LoginRequiredMixin, View):
    """Tela da pessoa: instruções, criar a chave (mostrada uma única vez) e revogar chaves."""

    def get(self, request, chave=None):
        return render(request, "assistente/desktop.html", self._contexto(request, chave))

    def post(self, request):
        nome = request.POST.get("nome", "").strip()[:60] or request.user.nome_curto
        _acesso, chave = AcessoApi.criar(request.user, nome)
        # A chave aparece só nesta resposta (não vai para a URL nem para o histórico do navegador).
        resposta = render(request, "assistente/desktop.html", self._contexto(request, chave))
        resposta["Cache-Control"] = "no-store"
        return resposta

    def _contexto(self, request, chave):
        acessos = list(request.user.acessos_api.all())
        ativos = [a for a in acessos if a.ativo]
        atual = ativos[0] if ativos else None  # a chave mais recente em uso
        usos = [a.ultimo_uso for a in ativos if a.ultimo_uso]
        # Andamento guardado no banco: sobrevive a recarregar a página e a trocar de computador.
        feitos = [
            bool(atual),
            any(x.instalador_baixado_em or x.ultimo_uso for x in ativos),  # com dois computadores há duas chaves ativas
            bool(usos),
            any(x.instrucoes_coladas_em for x in ativos),
        ]
        primeiro_pendente = feitos.index(False) if False in feitos else None
        passos = [
            {"feito": f, "estado": "feito" if f else ("atual" if i == primeiro_pendente else "espera")}
            for i, f in enumerate(feitos)
        ]
        return {
            "acessos": acessos, "chave": chave, "atual": atual, "passos": passos,
            "tudo_pronto": primeiro_pendente is None,
            "tem_chave": bool(ativos), "ultimo_uso": max(usos) if usos else None,
            "url": request.build_absolute_uri("/").rstrip("/"),
            "instrucoes": (CONECTOR / "instrucoes.md").read_text(encoding="utf-8"),
            "operacoes": list(OperacaoApi.objects.filter(usuario=request.user, grava=True)[:8]),
        }


class RevogarAcessoView(LoginRequiredMixin, View):
    def post(self, request, pk):
        get_object_or_404(AcessoApi, pk=pk, usuario=request.user).revogar()
        return redirect("assistente:desktop")


class ConectorDownloadView(LoginRequiredMixin, View):
    """Baixa o programa do conector (um arquivo Python que roda no computador da pessoa)."""

    def get(self, request):
        resposta = HttpResponse((CONECTOR / "celulares_mcp.py").read_bytes(), content_type="text/x-python; charset=utf-8")
        resposta["Content-Disposition"] = 'attachment; filename="celulares_mcp.py"'
        return resposta


def _arquivo_do_instalador(request, chave: str) -> HttpResponse:
    modelo = (CONECTOR / "instalador.cmd.modelo").read_text(encoding="utf-8")
    texto = modelo.replace("@@URL@@", request.build_absolute_uri("/").rstrip("/")).replace("@@CHAVE@@", chave)
    fim_de_linha = chr(13) + chr(10)  # o Windows espera CRLF nos arquivos .cmd
    resposta = HttpResponse(fim_de_linha.join(texto.splitlines()) + fim_de_linha, content_type="application/octet-stream")
    resposta["Content-Disposition"] = 'attachment; filename="Instalar-Claude-Desktop.cmd"'
    resposta["Cache-Control"] = "no-store"
    return resposta


class InstaladorDownloadView(LoginRequiredMixin, View):
    """Baixa o instalador (.cmd) já com a chave da pessoa dentro. Só aceita uma chave que seja dela."""

    def post(self, request):
        chave = request.POST.get("chave", "").strip()
        acesso = AcessoApi.por_chave(chave)
        if acesso is None or acesso.usuario_id != request.user.pk:
            return JsonResponse({"erro": "Chave inválida. Crie uma chave nova na tela."}, status=400)
        acesso.instalador_baixado_em = timezone.now()
        acesso.save(update_fields=["instalador_baixado_em"])
        return _arquivo_do_instalador(request, chave)


class RenovarInstaladorView(LoginRequiredMixin, View):
    """Gera um instalador novo para um computador que já tem chave: cria uma chave nova e revoga a antiga."""

    def post(self, request, pk):
        antigo = get_object_or_404(AcessoApi, pk=pk, usuario=request.user, revogado_em__isnull=True)
        novo, chave = antigo.renovar()
        novo.instalador_baixado_em = timezone.now()
        novo.save(update_fields=["instalador_baixado_em"])
        return _arquivo_do_instalador(request, chave)


class DesfazerOperacaoView(LoginRequiredMixin, View):
    """Desfaz um pagamento que o Claude registrou (estorna a baixa). Só a própria pessoa, e só uma vez."""

    def post(self, request, pk):
        from apps.pagamentos.models import Pagamento, RecebimentoCora

        operacao = get_object_or_404(OperacaoApi, pk=pk, usuario=request.user, grava=True, ok=True)
        pagamento_id = operacao.referencias.get("pagamento_id")
        if operacao.ferramenta != "registrar_pagamento" or not pagamento_id or operacao.desfeita_em:
            messages.error(request, "Esta operação não pode ser desfeita por aqui.")
            return redirect("assistente:desktop")
        with transaction.atomic():
            pagamento = Pagamento.objects.select_related("vencimento").filter(pk=pagamento_id).first()
            restante = Decimal("0.00")
            if pagamento is None:
                messages.info(request, "Este pagamento já tinha sido estornado.")
            else:
                # O Pix do extrato volta para "A registrar" (senão sumiria da lista sem ter pagamento).
                RecebimentoCora.objects.filter(pagamento=pagamento).update(
                    situacao=RecebimentoCora.Situacao.NOVO, pagamento=None, tratado_em=None, tratado_por=None,
                )
                restante = pagamento.estornar()
                messages.success(request, "Pagamento estornado. A parcela voltou a ficar em aberto.")
            operacao.desfeita_em = timezone.now()
            operacao.save(update_fields=["desfeita_em"])
        if restante:
            messages.warning(request, "Esta baixa havia transportado saldo para parcelas seguintes. Confira os valores previstos das próximas parcelas.")
        return redirect("assistente:desktop")


class InstrucoesColadasView(LoginRequiredMixin, View):
    """Marca (ou desmarca) que as instruções já foram coladas no Projeto do Claude Desktop."""

    def post(self, request):
        valor = timezone.now() if request.POST.get("feito") == "1" else None
        request.user.acessos_api.filter(revogado_em__isnull=True).update(instrucoes_coladas_em=valor)
        return redirect("assistente:desktop")
