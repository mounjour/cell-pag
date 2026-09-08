"""Webhook da Evolution API: atualiza o estado das mensagens de cobrança.

A Evolution não assina os eventos (a Meta assinava com HMAC). A autenticação
aqui é por **token compartilhado** (``EVOLUTION_WEBHOOK_TOKEN``), aceito no
cabeçalho ``apikey``/``Authorization`` ou em ``?token=``. Sem token configurado,
o endpoint só responde quando ``DEBUG=True`` (ambiente de desenvolvimento).
"""

import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Cobranca

logger = logging.getLogger("pagamentos.whatsapp")

# A Evolution manda o ACK como texto ("DELIVERY_ACK") ou como número (0..4).
_ACK_TEXTO = {
    "PENDING": None,
    "SERVER_ACK": Cobranca.Status.ENVIADO,
    "DELIVERY_ACK": Cobranca.Status.ENTREGUE,
    "READ": Cobranca.Status.LIDO,
    "PLAYED": Cobranca.Status.LIDO,
    "ERROR": Cobranca.Status.ERRO,
}
_ACK_NUMERO = {
    0: None,
    1: Cobranca.Status.ENVIADO,
    2: Cobranca.Status.ENTREGUE,
    3: Cobranca.Status.LIDO,
    4: Cobranca.Status.LIDO,
}
_ORDEM = {
    Cobranca.Status.PENDENTE: 0,
    Cobranca.Status.ERRO: 0,
    Cobranca.Status.ENVIADO: 1,
    Cobranca.Status.ENTREGUE: 2,
    Cobranca.Status.LIDO: 3,
}
_EVENTOS_ACEITOS = {"messages.update", "send.message", "messages.upsert", ""}


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(View):
    http_method_names = ["post"]

    def post(self, request):
        if not _token_valido(request):
            return HttpResponse("Token inválido.", status=403)
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponse("JSON inválido.", status=400)
        atualizadas = _processar(payload)
        return JsonResponse({"recebido": True, "atualizadas": atualizadas})


def _token_valido(request) -> bool:
    esperado = settings.EVOLUTION_WEBHOOK_TOKEN
    if not esperado:
        return settings.DEBUG
    recebido = (
        request.headers.get("apikey")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.GET.get("token", "")
    )
    return bool(recebido) and hmac.compare_digest(recebido, esperado)


def _eventos(payload):
    """Achata o payload da Evolution em uma sequência de dicts de status."""
    if isinstance(payload, list):
        for item in payload:
            yield from _eventos(item)
        return
    if not isinstance(payload, dict):
        return
    if payload.get("event", "") not in _EVENTOS_ACEITOS:
        return
    dados = payload.get("data", payload)
    if isinstance(dados, list):
        yield from (d for d in dados if isinstance(d, dict))
    elif isinstance(dados, dict):
        yield dados


def _novo_status(bruto):
    if isinstance(bruto, bool) or bruto is None:
        return None
    if isinstance(bruto, (int, float)):
        return _ACK_NUMERO.get(int(bruto))
    return _ACK_TEXTO.get(str(bruto).strip().upper())


def _processar(payload) -> int:
    atualizadas = 0
    for dado in _eventos(payload):
        identificador = (
            dado.get("keyId")
            or dado.get("messageId")
            or (dado.get("key") or {}).get("id")
        )
        novo = _novo_status(dado.get("status"))
        if not identificador or not novo:
            continue
        cobranca = Cobranca.objects.filter(id_externo=identificador).first()
        if not cobranca:
            continue
        if novo != Cobranca.Status.ERRO and _ORDEM[novo] < _ORDEM[cobranca.status]:
            continue
        agora = timezone.now()
        cobranca.status = novo
        campos = ["status", "atualizado_em"]
        if novo == Cobranca.Status.ENVIADO:
            cobranca.enviado_em = cobranca.enviado_em or agora
            campos.append("enviado_em")
        elif novo == Cobranca.Status.ENTREGUE:
            cobranca.entregue_em = agora
            campos.append("entregue_em")
        elif novo == Cobranca.Status.LIDO:
            cobranca.lido_em = agora
            campos.append("lido_em")
        else:
            cobranca.erro = str(dado.get("error") or "Falha informada pela Evolution")
            campos.append("erro")
        cobranca.save(update_fields=campos)
        atualizadas += 1
    return atualizadas
