"""Autenticação por token compartilhado dos webhooks (Evolution e Cora)."""

import hmac


def token_valido(request, esperado: str) -> bool:
    """True se o token da requisição bate com ``esperado``.

    Aceita o cabeçalho ``apikey``/``Authorization`` ou ``?token=``. Sem token
    configurado, rejeita tudo (falha fechado).
    """
    if not esperado:
        return False
    recebido = (
        request.headers.get("apikey")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.GET.get("token", "")
    )
    return bool(recebido) and hmac.compare_digest(recebido, esperado)
