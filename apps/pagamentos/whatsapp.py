"""Cliente da Evolution API para envio de mensagens de WhatsApp.

Substitui a WhatsApp Cloud API (Meta) — decisão do Alisson. A Evolution manda
texto livre, então não há mais templates aprovados: a mensagem montada em
``apps.pagamentos.cobranca`` vai inteira no corpo.
"""

import json
import logging
import re
import urllib.error
import urllib.parse
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


def mascara_numero(numero) -> str:
    """Telefone reduzido aos 4 últimos dígitos, para não vazar PII no log."""
    digitos = re.sub(r"\D", "", str(numero or ""))
    return "…" + digitos[-4:] if len(digitos) >= 4 else "…"


def _config_evolution():
    faltando = [
        nome
        for nome, valor in (
            ("EVOLUTION_API_URL", settings.EVOLUTION_API_URL),
            ("EVOLUTION_API_KEY", settings.EVOLUTION_API_KEY),
            ("EVOLUTION_INSTANCE", settings.EVOLUTION_INSTANCE),
        )
        if not valor
    ]
    if faltando:
        raise WhatsAppErro("Configuração Evolution incompleta: " + ", ".join(faltando))
    return (
        settings.EVOLUTION_API_URL.rstrip("/"),
        settings.EVOLUTION_API_KEY,
        settings.EVOLUTION_INSTANCE,
    )


def enviar_mensagem(*, destinatario: str, texto: str) -> dict:
    """Envia uma mensagem de texto, ou apenas simula conforme ``WHATSAPP_PROVIDER``.

    ``log`` só registra e devolve ``{"simulado": True, "id": ""}``.
    ``evolution`` chama ``POST {EVOLUTION_API_URL}/message/sendText/{instância}``.
    """
    provider = settings.WHATSAPP_PROVIDER.lower().strip()
    if provider == "log":
        logger.info(
            "[simulação WhatsApp -> %s] mensagem de %d caractere(s)",
            mascara_numero(destinatario),
            len(texto),
        )
        logger.debug("[simulação WhatsApp -> %s]\n%s", destinatario, texto)
        return {"simulado": True, "id": ""}
    if provider != "evolution":
        raise WhatsAppErro(f"WHATSAPP_PROVIDER desconhecido: {provider!r}")

    base_url, api_key, instancia = _config_evolution()
    url = f"{base_url}/message/sendText/{urllib.parse.quote(instancia)}"
    corpo = {"number": destinatario, "text": texto}
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"apikey": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=20) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Evolution respondeu HTTP %s: %s", exc.code, detalhe)
        raise WhatsAppErro(f"A Evolution recusou o envio (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Falha ao chamar a Evolution API: %s", exc)
        raise WhatsAppErro("Falha de comunicação com a Evolution API.") from exc

    identificador = (dados.get("key") or {}).get("id") or dados.get("id") or ""
    if not identificador:
        raise WhatsAppErro("A Evolution aceitou a requisição sem devolver o ID da mensagem.")
    return {"simulado": False, "id": identificador}
