"""Contador de "Cobrar hoje" para o menu.

Montar a agenda percorre todos os contratos ativos, então não dá para rodar em
toda página. Guardamos o número em cache por poucos segundos e o apagamos
sempre que algo que muda a agenda é salvo (baixa, parcela, contrato). O cache
é local a cada processo; com mais de um worker, os outros se atualizam pelo
TTL curto.
"""

from django.core.cache import cache
from django.utils import timezone

TTL_SEGUNDOS = 30


def _chave() -> str:
    return f"cobrar_hoje_n:{timezone.localdate().isoformat()}"


def _chave_bloqueio() -> str:
    return f"aparelhos_a_bloquear_n:{timezone.localdate().isoformat()}"


def _calcular_e_guardar() -> tuple[int, int]:
    """Monta a agenda uma vez e guarda os dois números (a cobrar hoje e a bloquear)."""
    from .agenda import montar_agenda_do_dia

    agenda = montar_agenda_do_dia()
    n, bloqueio = len(agenda["linhas"]), agenda["n_bloqueio"]
    cache.set(_chave(), n, TTL_SEGUNDOS)
    cache.set(_chave_bloqueio(), bloqueio, TTL_SEGUNDOS)
    return n, bloqueio


def contagem_cobrar_hoje() -> int:
    n = cache.get(_chave())
    if n is None:
        n = _calcular_e_guardar()[0]
    return n


def contagem_a_bloquear() -> int:
    """Contratos com 7 dias ou mais de atraso: hora de bloquear o aparelho (ação manual)."""
    n = cache.get(_chave_bloqueio())
    if n is None:
        n = _calcular_e_guardar()[1]
    return n


def invalidar(**_kwargs) -> None:
    cache.delete(_chave())
    cache.delete(_chave_bloqueio())


TTL_WHATSAPP_SEGUNDOS = 60
TTL_WHATSAPP_AO_VIVO_SEGUNDOS = 3


def status_whatsapp() -> str:
    """Estado da conexão do WhatsApp, em cache por pouco tempo.

    Lido em toda página (menu) — sem cache, cada carregamento faria uma
    chamada de rede à Evolution. ``"erro"`` cobre tanto desconexão quanto
    falha de comunicação: nos dois casos, alguém precisa olhar.
    """
    from .whatsapp import WhatsAppErro, obter_status_conexao

    chave = "whatsapp_status"
    estado = cache.get(chave)
    if estado is None:
        try:
            estado = obter_status_conexao()
        except WhatsAppErro:
            estado = "erro"
        cache.set(chave, estado, TTL_WHATSAPP_SEGUNDOS)
    return estado


def status_whatsapp_ao_vivo() -> str:
    """Estado do WhatsApp com cache de poucos segundos, pra tela consultar em loop.

    Várias abas (e pessoas) perguntando ao mesmo tempo dividem a mesma consulta
    à Evolution. Já atualiza o cache mais longo do menu, pra tudo concordar.
    """
    from .whatsapp import WhatsAppErro, obter_status_conexao

    chave = "whatsapp_status_ao_vivo"
    estado = cache.get(chave)
    if estado is None:
        try:
            estado = obter_status_conexao()
        except WhatsAppErro:
            estado = "erro"
        cache.set(chave, estado, TTL_WHATSAPP_AO_VIVO_SEGUNDOS)
        cache.set("whatsapp_status", estado, TTL_WHATSAPP_SEGUNDOS)
    return estado
