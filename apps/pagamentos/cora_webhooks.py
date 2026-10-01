"""Webhook da Cora: confirma a fatura na hora, sem esperar a rotina diária."""

import hashlib
import hmac
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from . import cora_api
from .models import CobrancaCora, EventoCora
from .pix_cora import sincronizar_cobranca

logger = logging.getLogger("pagamentos.cora")


def _token_valido(request) -> bool:
    esperado = settings.CORA_WEBHOOK_TOKEN
    if not esperado:
        return False
    recebido = (
        request.headers.get("apikey")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.GET.get("token", "")
    )
    return bool(recebido) and hmac.compare_digest(recebido, esperado)


@method_decorator(csrf_exempt, name="dispatch")
class CoraWebhookView(View):
    """Recebe o evento e confirma a fatura na hora (consulta autenticada à Cora).

    A Cora documenta os dados do evento em cabeçalhos, mas não uma assinatura
    criptográfica. Por isso este endpoint (a) exige um token compartilhado
    (``CORA_WEBHOOK_TOKEN``, passado como ``?token=`` na URL cadastrada na
    Cora), (b) só aceita IDs de faturas que já existem localmente e (c) cria no
    máximo um sinal por fatura/tipo. O evento em si não é a fonte da verdade —
    só dispara ``sincronizar_cobranca``, que busca o status real na API
    autenticada antes de dar a baixa (mesmo caminho usado pela rotina diária e
    pelo botão manual). Se a consulta à Cora falhar, o evento fica registrado
    sem erro fatal: a rotina diária (``reconciliar_abertas``) cobre de
    qualquer forma, mais tarde.
    """

    http_method_names = ["post"]

    def post(self, request):
        if not _token_valido(request):
            return HttpResponse("Token inválido.", status=403)
        tipo = request.headers.get("webhook-event-type", "")
        recurso_id = request.headers.get("webhook-resource-id", "")
        if not tipo.startswith("invoice.") or not recurso_id:
            return JsonResponse({"success": False, "erro": "Evento inválido."}, status=400)
        cobranca = CobrancaCora.objects.filter(cora_id=recurso_id).first()
        if cobranca is None:
            return JsonResponse({"success": True, "localizada": False})

        # Chave determinística limita replays e impede crescimento ilimitado da
        # tabela por cabeçalhos de evento inventados.
        evento_id = hashlib.sha256(f"{tipo}:{recurso_id}".encode()).hexdigest()
        _, criado = EventoCora.objects.get_or_create(
            evento_id=evento_id,
            defaults={"tipo": tipo, "recurso_id": recurso_id},
        )

        try:
            sincronizar_cobranca(cobranca)
            EventoCora.objects.filter(evento_id=evento_id).update(
                processado=True, erro="", processado_em=timezone.now()
            )
        except cora_api.CoraErro as exc:
            EventoCora.objects.filter(evento_id=evento_id).update(erro=str(exc))
            logger.warning("Webhook Cora: falha ao sincronizar %s: %s", recurso_id, exc)

        return JsonResponse({"success": True, "registrado": criado})
