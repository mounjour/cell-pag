"""Webhook da Cora: apenas registra sinais para faturas já conhecidas."""

import hashlib
import hmac

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import CobrancaCora, EventoCora


def _token_valido(request) -> bool:
    esperado = settings.CORA_WEBHOOK_TOKEN
    if not esperado:
        return settings.DEBUG
    recebido = (
        request.headers.get("apikey")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.GET.get("token", "")
    )
    return bool(recebido) and hmac.compare_digest(recebido, esperado)


@method_decorator(csrf_exempt, name="dispatch")
class CoraWebhookView(View):
    """Recebe o evento sem executar nenhuma operação bancária autenticada.

    A Cora documenta os dados do evento em cabeçalhos, mas não uma assinatura
    criptográfica. Por isso este endpoint (a) exige um token compartilhado
    (``CORA_WEBHOOK_TOKEN``, passado como ``?token=`` na URL cadastrada na
    Cora), (b) só aceita IDs de faturas que já existem localmente e (c) cria no
    máximo um sinal por fatura/tipo. A confirmação e a baixa ficam para o
    reconciliador interno.
    """

    http_method_names = ["post"]

    def post(self, request):
        if not _token_valido(request):
            return HttpResponse("Token inválido.", status=403)
        tipo = request.headers.get("webhook-event-type", "")
        recurso_id = request.headers.get("webhook-resource-id", "")
        if not tipo.startswith("invoice.") or not recurso_id:
            return JsonResponse({"success": False, "erro": "Evento inválido."}, status=400)
        if not CobrancaCora.objects.filter(cora_id=recurso_id).exists():
            return JsonResponse({"success": True, "localizada": False})

        # Chave determinística limita replays e impede crescimento ilimitado da
        # tabela por cabeçalhos de evento inventados.
        evento_id = hashlib.sha256(f"{tipo}:{recurso_id}".encode()).hexdigest()
        _, criado = EventoCora.objects.get_or_create(
            evento_id=evento_id,
            defaults={"tipo": tipo, "recurso_id": recurso_id},
        )
        return JsonResponse({"success": True, "registrado": criado})
