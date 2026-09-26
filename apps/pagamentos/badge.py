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


def contagem_cobrar_hoje() -> int:
    from .agenda import montar_agenda_do_dia

    n = cache.get(_chave())
    if n is None:
        n = len(montar_agenda_do_dia()["linhas"])
        cache.set(_chave(), n, TTL_SEGUNDOS)
    return n


def invalidar(**_kwargs) -> None:
    cache.delete(_chave())
