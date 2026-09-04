"""Cliente mínimo da API oficial WhatsApp Cloud API."""

import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger("pagamentos.whatsapp")


class WhatsAppErro(RuntimeError):
    pass


def numero_so_digitos(numero) -> str:
    try:
        numero = numero.as_e164
    except AttributeError:
        numero = str(numero or "")
    return re.sub(r"\D", "", numero)


def enviar_template(*, destinatario: str, template: str, parametros: list[str]) -> dict:
    """Envia um template ou apenas simula, conforme ``WHATSAPP_PROVIDER``."""
    provider = settings.WHATSAPP_PROVIDER.lower().strip()
    if provider == "log":
        logger.info(
            "[simulação WhatsApp -> %s] template=%s parametros=%s",
            destinatario,
            template,
            parametros,
        )
        return {"simulado": True, "id": ""}
    if provider != "meta":
        raise WhatsAppErro(f"WHATSAPP_PROVIDER desconhecido: {provider!r}")

    faltando = [
        nome
        for nome, valor in (
            ("WHATSAPP_GRAPH_VERSION", settings.WHATSAPP_GRAPH_VERSION),
            ("WHATSAPP_PHONE_NUMBER_ID", settings.WHATSAPP_PHONE_NUMBER_ID),
            ("WHATSAPP_ACCESS_TOKEN", settings.WHATSAPP_ACCESS_TOKEN),
        )
        if not valor
    ]
    if faltando:
        raise WhatsAppErro("Configuração incompleta: " + ", ".join(faltando))

    url = (
        f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    corpo = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": destinatario,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "pt_BR"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in parametros],
                }
            ],
        },
    }
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=20) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", errors="replace")[:1000]
        raise WhatsAppErro(f"Meta respondeu HTTP {exc.code}: {detalhe}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WhatsAppErro(f"Falha ao chamar a API do WhatsApp: {exc}") from exc

    mensagens = dados.get("messages") or []
    if not mensagens or not mensagens[0].get("id"):
        raise WhatsAppErro("A Meta aceitou a requisição sem devolver o ID da mensagem.")
    return {"simulado": False, "id": mensagens[0]["id"]}
