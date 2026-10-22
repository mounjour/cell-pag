"""API do conector do Claude Desktop e a tela onde cada pessoa cria a sua chave de acesso.

A API fala só JSON, autentica por chave (``Authorization: Bearer cp_...``) e registra tudo em ``OperacaoApi``.
Quem autoriza cada gravação é a pessoa, no pedido de permissão do Claude Desktop, antes da chamada chegar aqui.
"""

import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
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

    def dispatch(self, request, *args, **kwargs):
        acesso = _acesso_da_requisicao(request)
        if acesso is None:
            return JsonResponse({"erro": "Chave de acesso ausente, inválida ou revogada."}, status=401)
        if not _dentro_do_limite(acesso):
            return JsonResponse({"erro": "Muitas chamadas na última hora. Tente de novo daqui a pouco."}, status=429)
        request.acesso = acesso
        acesso.ultimo_uso = timezone.now()
        acesso.save(update_fields=["ultimo_uso"])
        return super().dispatch(request, *args, **kwargs)


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
            texto, resumo, gravou = ferramentas.executar_ferramenta(nome, parametros, acesso.usuario)
            ok, status = True, 200
        except ferramentas.ErroFerramenta as exc:
            texto, resumo, gravou, ok, status = str(exc), "", False, False, 400
        except Exception:  # noqa: BLE001 — um erro numa ferramenta não pode derrubar a API
            logger.exception("Falha na ferramenta %s do Claude Desktop", nome)
            texto, resumo, gravou, ok, status = "Erro interno ao executar esta ferramenta.", "", False, False, 500
        if grava or not ok:
            OperacaoApi.objects.create(
                acesso=acesso, usuario=acesso.usuario, ferramenta=nome[:40], grava=grava,
                parametros={k: v for k, v in parametros.items()}, resumo=resumo or str(parametros.get("resumo", ""))[:300],
                ok=ok, resultado=texto[:2000],
            )
        return JsonResponse({"ok": ok, "resultado" if ok else "erro": texto, "gravou": gravou}, status=status)


CONECTOR = settings.BASE_DIR / "apps" / "assistente" / "conector"


class AcessoDesktopView(LoginRequiredMixin, View):
    """Tela da pessoa: instruções, criar a chave (mostrada uma única vez) e revogar chaves."""

    def get(self, request, chave=None):
        return render(request, "assistente/desktop.html", self._contexto(request, chave))

    def post(self, request):
        nome = request.POST.get("nome", "").strip()[:60] or "Claude Desktop"
        _acesso, chave = AcessoApi.criar(request.user, nome)
        # A chave aparece só nesta resposta (não vai para a URL nem para o histórico do navegador).
        resposta = render(request, "assistente/desktop.html", self._contexto(request, chave))
        resposta["Cache-Control"] = "no-store"
        return resposta

    def _contexto(self, request, chave):
        return {
            "acessos": list(request.user.acessos_api.all()), "chave": chave,
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
