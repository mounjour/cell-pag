"""Cliente HTTP mTLS para a Integração Direta da Cora.

Falha transitória (timeout, erro 5xx, "429 Too Many Requests") tem retry com
espera crescente (`CORA_RETRY_TENTATIVAS` / `CORA_RETRY_ESPERA_BASE_SEGUNDOS`).
Isso é seguro e não gera custo extra: os termos da Cora só cobram por QR code
Pix **compensado** (pago) — não por cobrança criada, tentativa ou chamada de
API que falhe (<https://www.cora.com.br/termos-e-condicoes-de-apis/>) — e
`criar_fatura()` sempre manda o mesmo `Idempotency-Key` por `Vencimento`
(`CobrancaCora.idempotency_key`), então repetir a chamada não duplica a
fatura. Erro definitivo (4xx que não seja 429, ou fim das tentativas) sobe
como `CoraErro` e a cobrança fica com `status=ERRO`, visível no painel Pix
para a Yslane tentar de novo manualmente.
"""

import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger("pagamentos.cora")


class CoraErro(RuntimeError):
    pass


_token_cache = {"valor": "", "expira_em": 0.0}


def _configuracao():
    valores = {
        "CORA_CLIENT_ID": settings.CORA_CLIENT_ID,
        "CORA_CERT_PATH": settings.CORA_CERT_PATH,
        "CORA_KEY_PATH": settings.CORA_KEY_PATH,
        "CORA_TOKEN_URL": settings.CORA_TOKEN_URL,
        "CORA_API_BASE_URL": settings.CORA_API_BASE_URL,
    }
    faltando = [nome for nome, valor in valores.items() if not valor]
    if faltando:
        raise CoraErro("Configuração Cora incompleta: " + ", ".join(faltando))
    return valores


def _contexto_ssl(config):
    contexto = ssl.create_default_context()
    try:
        contexto.load_cert_chain(config["CORA_CERT_PATH"], config["CORA_KEY_PATH"])
    except (OSError, ssl.SSLError) as exc:
        raise CoraErro(f"Não foi possível carregar o certificado/chave da Cora: {exc}") from exc
    return contexto


def obter_token(*, renovar=False) -> str:
    agora = time.time()
    if not renovar and _token_cache["valor"] and agora < _token_cache["expira_em"]:
        return _token_cache["valor"]
    config = _configuracao()
    dados = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": config["CORA_CLIENT_ID"]}
    ).encode()
    requisicao = urllib.request.Request(
        config["CORA_TOKEN_URL"],
        data=dados,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    resposta = _abrir(requisicao, contexto=_contexto_ssl(config), autenticada=False)
    token = resposta.get("access_token")
    if not token:
        raise CoraErro("A Cora não devolveu um token de acesso.")
    expira = int(resposta.get("expires_in", 3600))
    _token_cache.update(valor=token, expira_em=agora + max(60, expira - 60))
    return token


def criar_fatura(payload: dict, idempotency_key) -> dict:
    return _requisicao_api(
        "/v2/invoices/",
        metodo="POST",
        payload=payload,
        cabecalhos={"Idempotency-Key": str(idempotency_key)},
    )


def consultar_fatura(cora_id: str) -> dict:
    return _requisicao_api(f"/v2/invoices/{urllib.parse.quote(cora_id)}", metodo="GET")


def cancelar_fatura(cora_id: str) -> dict:
    """Cancela uma fatura em aberto (DELETE /v2/invoices/{id})."""
    return _requisicao_api(f"/v2/invoices/{urllib.parse.quote(cora_id)}", metodo="DELETE")


def _requisicao_api(caminho, *, metodo, payload=None, cabecalhos=None, repetir_401=True):
    config = _configuracao()
    url = config["CORA_API_BASE_URL"].rstrip("/") + caminho
    headers = {
        "Authorization": f"Bearer {obter_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        **(cabecalhos or {}),
    }
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=metodo,
    )
    try:
        return _abrir(requisicao, contexto=_contexto_ssl(config), autenticada=True)
    except CoraErroNaoAutorizado:
        if not repetir_401:
            raise
        obter_token(renovar=True)
        return _requisicao_api(
            caminho,
            metodo=metodo,
            payload=payload,
            cabecalhos=cabecalhos,
            repetir_401=False,
        )


class CoraErroNaoAutorizado(CoraErro):
    pass


#: Códigos HTTP considerados falha transitória — vale repetir a chamada.
_HTTP_TRANSITORIO = {429, 500, 502, 503, 504}


def _abrir(requisicao, *, contexto, autenticada):
    tentativas = max(1, settings.CORA_RETRY_TENTATIVAS)
    espera_base = settings.CORA_RETRY_ESPERA_BASE_SEGUNDOS
    for tentativa in range(1, tentativas + 1):
        ultima = tentativa == tentativas
        try:
            with urllib.request.urlopen(requisicao, context=contexto, timeout=25) as resposta:
                corpo = resposta.read()
                return json.loads(corpo.decode("utf-8")) if corpo else {}
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
            if autenticada and exc.code == 401:
                raise CoraErroNaoAutorizado("Token Cora expirado ou inválido.") from exc
            # O corpo da resposta pode repetir dados do cliente que enviamos — fica
            # só no log do servidor, nunca na mensagem exibida na tela.
            logger.warning(
                "Cora respondeu HTTP %s (tentativa %s/%s): %s",
                exc.code, tentativa, tentativas, detalhe,
            )
            if ultima or exc.code not in _HTTP_TRANSITORIO:
                raise CoraErro(f"A Cora recusou a requisição (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning(
                "Falha de comunicação com a Cora (tentativa %s/%s): %s",
                tentativa, tentativas, exc,
            )
            if ultima:
                raise CoraErro("Falha de comunicação com a Cora.") from exc
        time.sleep(espera_base * (2 ** (tentativa - 1)))
