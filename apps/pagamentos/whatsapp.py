"""Cliente da Evolution API para envio de mensagens de WhatsApp.

Substitui a WhatsApp Cloud API (Meta) — decisão do Alisson. A Evolution manda
texto livre, então não há mais templates aprovados: a mensagem montada em
``apps.pagamentos.cobranca`` vai inteira no corpo.
"""

import json
import logging
import re
import time
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


def _recusa(codigo: int, detalhe: str) -> str:
    """Texto do erro de uma recusa da Evolution, com o motivo quando ele ajuda a decidir o que fazer."""
    texto = f"A Evolution recusou a operação (HTTP {codigo})."
    if '"exists":false' in detalhe.replace(" ", ""):
        return texto + " O número não tem WhatsApp (confira o telefone do cliente)."
    try:
        corpo = json.loads(detalhe)
        motivo = corpo.get("response", {}).get("message") or corpo.get("message") or corpo.get("error")
    except (ValueError, AttributeError):
        motivo = None
    if motivo:
        texto += f" Motivo: {str(motivo)[:160]}"
    return texto


def _chamar_evolution(caminho: str, corpo: dict, metodo: str = "POST") -> dict:
    base_url, api_key, instancia = _config_evolution()
    url = f"{base_url}{caminho}/{urllib.parse.quote(instancia)}"
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"apikey": api_key, "Content-Type": "application/json"},
        method=metodo,
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=20) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Evolution respondeu HTTP %s: %s", exc.code, detalhe)
        raise WhatsAppErro(_recusa(exc.code, detalhe)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Falha ao chamar a Evolution API: %s", exc)
        raise WhatsAppErro("Falha de comunicação com a Evolution API.") from exc


def _extrair_id_mensagem(dados: dict) -> str:
    identificador = (dados.get("key") or {}).get("id") or dados.get("id") or ""
    if not identificador:
        raise WhatsAppErro("A Evolution aceitou a requisição sem devolver o ID da mensagem.")
    return identificador


def _chamar_evolution_get(caminho: str, consulta: dict | None = None):
    base_url, api_key, instancia = _config_evolution()
    url = f"{base_url}{caminho}/{urllib.parse.quote(instancia)}"
    if consulta:
        url += "?" + urllib.parse.urlencode(consulta)
    requisicao = urllib.request.Request(url, headers={"apikey": api_key})
    try:
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Evolution respondeu HTTP %s: %s", exc.code, detalhe)
        raise WhatsAppErro(_recusa(exc.code, detalhe)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Falha ao chamar a Evolution API: %s", exc)
        raise WhatsAppErro("Falha de comunicação com a Evolution API.") from exc


def consultar_grupos() -> dict:
    """Pergunta à Evolution quais grupos o número conectado tem, sem cache e **levantando** o erro (usado no diagnóstico).

    Devolve ``{"grupos": [{"id", "nome", "participantes"}] por nome, "recebidos": quantos itens a Evolution mandou,
    "ignorados": itens que não são grupo (@g.us), "segundos": quanto demorou}``."""
    if settings.WHATSAPP_PROVIDER.lower().strip() != "evolution":
        raise WhatsAppErro("Modo simulação (WHATSAPP_PROVIDER != evolution): não há grupos para listar.")
    inicio = time.monotonic()
    dados = _chamar_evolution_get("/group/fetchAllGroups", {"getParticipants": "false"})
    itens = dados if isinstance(dados, list) else []
    grupos = sorted(
        (
            {"id": g["id"], "nome": str(g.get("subject") or g["id"]), "participantes": int(g.get("size") or 0)}
            for g in itens
            if isinstance(g, dict) and str(g.get("id", "")).endswith("@g.us")
        ),
        key=lambda g: g["nome"].lower(),
    )
    ignorados = [str(g.get("id", g))[:40] if isinstance(g, dict) else str(g)[:40] for g in itens if not (isinstance(g, dict) and str(g.get("id", "")).endswith("@g.us"))]
    if not isinstance(dados, list):
        ignorados.append(f"resposta que não é uma lista: {str(dados)[:120]}")
    logger.info("Evolution devolveu %d item(ns), %d grupo(s), em %.1fs.", len(itens), len(grupos), time.monotonic() - inicio)
    return {"grupos": grupos, "recebidos": len(itens), "ignorados": ignorados, "segundos": round(time.monotonic() - inicio, 1)}


def grupos_do_whatsapp(forcar: bool = False) -> list[dict] | None:
    """Grupos em que o número da empresa está: ``[{"id", "nome", "participantes"}]`` por nome.

    ``None`` quando não dá para saber (modo simulação, Evolution fora do ar): quem chama cai no cadastro manual.
    O resultado fica em cache por 1 minuto (a lista é pesada para a Evolution); ``forcar`` ignora o cache."""
    from django.core.cache import cache

    if settings.WHATSAPP_PROVIDER.lower().strip() != "evolution":
        return None
    if forcar:
        cache.delete("whatsapp_grupos")
    guardado = cache.get("whatsapp_grupos")
    if guardado is not None:
        return guardado
    try:
        grupos = consultar_grupos()["grupos"]
    except WhatsAppErro as exc:
        logger.warning("Não consegui listar os grupos do WhatsApp: %s", exc)
        return None
    cache.set("whatsapp_grupos", grupos, 60)
    return grupos


def jid_do_destino(destinatario: str) -> str:
    """Identificador que a Evolution usa na conversa: o do grupo como está, ou o telefone com ``@s.whatsapp.net``."""
    if "@" in str(destinatario):
        return str(destinatario)
    return f"{numero_so_digitos(destinatario)}@s.whatsapp.net"


def obter_status_conexao() -> str:
    """``"open"`` (conectado), ``"close"`` (desconectado) ou outro estado da Evolution.

    ``log`` (modo simulação, sem Evolution configurada) devolve ``"simulado"``.
    """
    if settings.WHATSAPP_PROVIDER.lower().strip() != "evolution":
        return "simulado"
    dados = _chamar_evolution_get("/instance/connectionState")
    return (dados.get("instance") or {}).get("state", "")


def conexao_caiu(erro) -> bool:
    """O erro é o de uma conexão morta ("Connection Closed"): reiniciar a conexão costuma resolver."""
    return "connection closed" in str(erro).lower()


def reiniciar_conexao() -> str:
    """Reinicia a conexão com o WhatsApp **sem perder a sessão** (não precisa de QR).

    A Evolution fecha o socket e reconecta com a sessão guardada. Se ela já sabe que está desconectada (estado
    ``close``), recusa o restart; aí pede a reconexão. Devolve ``"reiniciada"`` ou ``"reconectada"``;
    levanta ``WhatsAppErro`` se nenhuma das duas funcionar (aí só lendo o QR de novo)."""
    if settings.WHATSAPP_PROVIDER.lower().strip() != "evolution":
        raise WhatsAppErro("Modo simulação (WHATSAPP_PROVIDER != evolution): não há conexão para reiniciar.")
    try:
        dados = _chamar_evolution("/instance/restart", {})
    except WhatsAppErro as exc:
        if "not connected" not in str(exc).lower():
            raise
        dados = _chamar_evolution_get("/instance/connect")
        acao = "reconectada"
    else:
        acao = "reiniciada"
    if isinstance(dados, dict) and dados.get("error"):  # a Evolution devolve o erro no corpo, com status 200
        raise WhatsAppErro(f"A Evolution não conseguiu reiniciar a conexão: {str(dados.get('message', ''))[:160]}")
    return acao


def desconectar_sessao() -> None:
    """Encerra a sessão do WhatsApp na Evolution (logout), para ler um QR novo.

    Serve quando a sessão fica presa: a Evolution diz "open", mas as mensagens falham com "Connection Closed"."""
    if settings.WHATSAPP_PROVIDER.lower().strip() != "evolution":
        raise WhatsAppErro("Modo simulação (WHATSAPP_PROVIDER != evolution): não há sessão para reiniciar.")
    _chamar_evolution("/instance/logout", {}, "DELETE")


def obter_qrcode() -> str:
    """Pede um QR code novo pra conectar (ou reconectar) o WhatsApp.

    Devolve a imagem já como data URI (``data:image/png;base64,...``), pronta
    pro atributo ``src`` de uma ``<img>``. O QR expira rápido (segundos) — quem
    chama deve mostrar na hora, sem guardar pra depois.
    """
    if settings.WHATSAPP_PROVIDER.lower().strip() != "evolution":
        raise WhatsAppErro("Modo simulação (WHATSAPP_PROVIDER != evolution): não há QR code.")
    dados = _chamar_evolution_get("/instance/connect")
    qr = dados.get("base64", "")
    if not qr:
        raise WhatsAppErro("A Evolution não devolveu um QR code (talvez já esteja conectado).")
    return qr


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

    dados = _chamar_evolution(
        "/message/sendText",
        {"number": destinatario, "text": texto},
    )
    return {"simulado": False, "id": _extrair_id_mensagem(dados)}


def enviar_imagem(*, destinatario: str, imagem_url: str, legenda: str) -> dict:
    """Envia uma imagem (o QR code Pix) com a mensagem como legenda.

    ``log`` só registra e devolve ``{"simulado": True, "id": ""}``.
    ``evolution`` chama ``POST {EVOLUTION_API_URL}/message/sendMedia/{instância}``.
    """
    provider = settings.WHATSAPP_PROVIDER.lower().strip()
    if provider == "log":
        logger.info(
            "[simulação WhatsApp -> %s] imagem + legenda de %d caractere(s)",
            mascara_numero(destinatario),
            len(legenda),
        )
        logger.debug("[simulação WhatsApp -> %s]\n%s\n%s", destinatario, imagem_url, legenda)
        return {"simulado": True, "id": ""}
    if provider != "evolution":
        raise WhatsAppErro(f"WHATSAPP_PROVIDER desconhecido: {provider!r}")

    dados = _chamar_evolution(
        "/message/sendMedia",
        {
            "number": destinatario,
            "mediatype": "image",
            "media": imagem_url,
            "caption": legenda,
            "fileName": "qrcode-pix.png",
        },
    )
    return {"simulado": False, "id": _extrair_id_mensagem(dados)}


def apagar_mensagem(*, destinatario: str, id_mensagem: str) -> dict:
    """Apaga, para os dois lados, uma mensagem que enviamos ao cliente.

    ``log`` só registra e devolve ``{"simulado": True}``.
    ``evolution`` chama ``DELETE {EVOLUTION_API_URL}/chat/deleteMessageForEveryone/{instância}``.
    O WhatsApp só deixa apagar para todos dentro de uma janela de tempo depois do
    envio; passada a janela, a Evolution recusa e isto levanta ``WhatsAppErro``.
    """
    provider = settings.WHATSAPP_PROVIDER.lower().strip()
    if provider == "log":
        logger.info("[simulação WhatsApp -> %s] apagar mensagem", mascara_numero(destinatario))
        return {"simulado": True}
    if provider != "evolution":
        raise WhatsAppErro(f"WHATSAPP_PROVIDER desconhecido: {provider!r}")

    _chamar_evolution(
        "/chat/deleteMessageForEveryone",
        {
            "id": id_mensagem,
            "remoteJid": jid_do_destino(destinatario),
            "fromMe": True,
        },
        metodo="DELETE",
    )
    return {"simulado": False}
