import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View

from . import ferramentas, servico
from .models import Acao, Conversa


def _conversa_ativa(usuario) -> Conversa:
    return usuario.conversas_assistente.order_by("-pk").first() or Conversa.objects.create(usuario=usuario)


def _acao_json(acao: Acao) -> dict:
    return {
        "id": acao.pk, "resumo": acao.resumo, "avisos": acao.avisos, "estado": acao.estado,
        "estado_rotulo": acao.get_estado_display(), "resultado": acao.resultado,
        "confirmar_url": reverse("assistente:confirmar", args=[acao.pk]),
        "cancelar_url": reverse("assistente:cancelar", args=[acao.pk]),
    }


class HistoricoView(LoginRequiredMixin, View):
    """Conversa atual (mensagens e propostas) para o balão preencher ao abrir."""

    def get(self, request):
        conversa = _conversa_ativa(request.user)
        acoes = list(conversa.acoes.all())
        return JsonResponse({
            "configurado": servico.configurado(),
            "mensagens": servico.texto_das_mensagens(conversa),
            "pendentes": [_acao_json(a) for a in acoes if a.estado == Acao.Estado.PENDENTE],
            "decididas": [_acao_json(a) for a in acoes if a.estado != Acao.Estado.PENDENTE][-6:],
        })


class EnviarView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            texto = str(json.loads(request.body or b"{}").get("texto", "")).strip()
        except ValueError:
            texto = ""
        if not texto:
            return JsonResponse({"erro": "Escreva uma mensagem."}, status=400)
        if len(texto) > 2000:
            return JsonResponse({"erro": "Mensagem longa demais (máximo 2.000 letras)."}, status=400)
        conversa = _conversa_ativa(request.user)
        try:
            resultado = servico.responder(conversa, texto, request.user)
        except servico.AssistenteIndisponivel as exc:
            return JsonResponse({"erro": str(exc)}, status=503)
        return JsonResponse({"resposta": resultado["resposta"], "acoes": [_acao_json(a) for a in resultado["acoes"]]})


class _AcaoView(LoginRequiredMixin, View):
    def _acao(self, request, pk) -> Acao:
        return get_object_or_404(Acao, pk=pk, conversa__usuario=request.user)


class AcaoConfirmarView(_AcaoView):
    def post(self, request, pk):
        acao = self._acao(request, pk)
        try:
            servico.confirmar(acao, request.user)
        except ferramentas.ErroFerramenta as exc:
            return JsonResponse({"erro": str(exc)}, status=409)
        return JsonResponse(_acao_json(acao))


class AcaoCancelarView(_AcaoView):
    def post(self, request, pk):
        acao = self._acao(request, pk)
        try:
            servico.cancelar(acao, request.user)
        except ferramentas.ErroFerramenta as exc:
            return JsonResponse({"erro": str(exc)}, status=409)
        return JsonResponse(_acao_json(acao))


class NovaConversaView(LoginRequiredMixin, View):
    def post(self, request):
        for acao in Acao.objects.filter(conversa__usuario=request.user, estado=Acao.Estado.PENDENTE):
            servico.cancelar(acao, request.user)
        Conversa.objects.create(usuario=request.user)
        return JsonResponse({"ok": True})
