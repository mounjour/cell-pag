"""Webhook de status das mensagens enviadas pela Meta."""

import hashlib
import hmac
import json
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Cobranca


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(View):
    def get(self, request):
        if (
            request.GET.get("hub.mode") == "subscribe"
            and settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
            and hmac.compare_digest(
                request.GET.get("hub.verify_token", ""),
                settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN,
            )
        ):
            return HttpResponse(request.GET.get("hub.challenge", ""))
        return HttpResponse("Verificação recusada.", status=403)

    def post(self, request):
        if not _assinatura_valida(request.body, request.headers.get("X-Hub-Signature-256", "")):
            return HttpResponse("Assinatura inválida.", status=403)
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponse("JSON inválido.", status=400)
        atualizadas = _processar_status(payload)
        return JsonResponse({"recebido": True, "atualizadas": atualizadas})


def _assinatura_valida(corpo: bytes, recebida: str) -> bool:
    segredo = settings.WHATSAPP_APP_SECRET
    if not segredo:
        return settings.DEBUG
    esperada = "sha256=" + hmac.new(
        segredo.encode("utf-8"), corpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(recebida, esperada)


def _processar_status(payload: dict) -> int:
    ordem = {
        Cobranca.Status.PENDENTE: 0,
        Cobranca.Status.ERRO: 0,
        Cobranca.Status.ENVIADO: 1,
        Cobranca.Status.ENTREGUE: 2,
        Cobranca.Status.LIDO: 3,
    }
    mapeamento = {
        "sent": Cobranca.Status.ENVIADO,
        "delivered": Cobranca.Status.ENTREGUE,
        "read": Cobranca.Status.LIDO,
        "failed": Cobranca.Status.ERRO,
    }
    atualizadas = 0
    for entrada in payload.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for status_api in mudanca.get("value", {}).get("statuses", []):
                novo = mapeamento.get(status_api.get("status"))
                identificador = status_api.get("id")
                if not novo or not identificador:
                    continue
                cobranca = Cobranca.objects.filter(id_externo=identificador).first()
                if not cobranca:
                    continue
                if novo != Cobranca.Status.ERRO and ordem[novo] < ordem[cobranca.status]:
                    continue
                instante = _instante(status_api.get("timestamp"))
                cobranca.status = novo
                campos = ["status", "atualizado_em"]
                if novo == Cobranca.Status.ENVIADO:
                    cobranca.enviado_em = cobranca.enviado_em or instante
                    campos.append("enviado_em")
                elif novo == Cobranca.Status.ENTREGUE:
                    cobranca.entregue_em = instante
                    campos.append("entregue_em")
                elif novo == Cobranca.Status.LIDO:
                    cobranca.lido_em = instante
                    campos.append("lido_em")
                else:
                    erros = status_api.get("errors") or []
                    cobranca.erro = str(erros[0].get("title", "Falha informada pela Meta")) if erros else "Falha informada pela Meta"
                    campos.append("erro")
                cobranca.save(update_fields=campos)
                atualizadas += 1
    return atualizadas


def _instante(timestamp):
    try:
        return datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        return timezone.now()
