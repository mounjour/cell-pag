"""Contador de "Cobrar hoje" para o menu.

Montar a agenda percorre todos os contratos ativos, então não dá para rodar em
toda página. Guardamos o número em cache por poucos segundos e o apagamos
sempre que algo que muda a agenda é salvo (baixa, parcela, contrato). O cache
é local a cada processo; com mais de um worker, os outros se atualizam pelo
TTL curto.
"""

import logging
import threading

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

TTL_SEGUNDOS = 30
TTL_ANTIGO_SEGUNDOS = 60 * 60 * 24

_trava = threading.Lock()
_em_renovacao: set[str] = set()


def _renovar(chave: str, calcular, ttl: int) -> None:
    """Recalcula numa thread (uma por chave), sem segurar a página de ninguém."""
    with _trava:
        if chave in _em_renovacao:
            return
        _em_renovacao.add(chave)

    def trabalho():
        from django.db import connection

        try:
            valor = calcular()
            cache.set(chave, valor, ttl)
            cache.set(chave + ":antigo", valor, TTL_ANTIGO_SEGUNDOS)
        except Exception:
            logger.warning("Falha ao renovar %s em segundo plano.", chave, exc_info=True)
        finally:
            connection.close()
            with _trava:
                _em_renovacao.discard(chave)

    threading.Thread(target=trabalho, daemon=True).start()


def sem_espera(chave: str, calcular, ttl: int, padrao=None, bloquear_se_vazio: bool = True):
    """Valor em cache; vencido, devolve a cópia antiga na hora e renova em segundo plano.

    Só espera o cálculo quando nunca houve valor e ``bloquear_se_vazio`` (contas de banco, rápidas). Para
    chamadas de rede use ``bloquear_se_vazio=False``: sem valor algum, devolve ``padrao`` e calcula depois."""
    valor = cache.get(chave)
    if valor is not None:
        return valor
    antigo = cache.get(chave + ":antigo")
    if antigo is not None:
        _renovar(chave, calcular, ttl)
        return antigo
    if bloquear_se_vazio:
        valor = calcular()
        cache.set(chave, valor, ttl)
        cache.set(chave + ":antigo", valor, TTL_ANTIGO_SEGUNDOS)
        return valor
    _renovar(chave, calcular, ttl)
    return padrao


def _apagar(chave: str) -> None:
    cache.delete(chave)
    cache.delete(chave + ":antigo")


def _chave() -> str:
    return f"agenda_contagens:{timezone.localdate().isoformat()}"


def _agenda_contagens() -> tuple[int, int]:
    """Monta a agenda uma vez e devolve os dois números (a cobrar hoje e a bloquear)."""
    from .agenda import montar_agenda_do_dia

    agenda = montar_agenda_do_dia()
    return len(agenda["linhas"]), agenda["n_bloqueio"]


def _contagens() -> tuple[int, int]:
    return sem_espera(_chave(), _agenda_contagens, TTL_SEGUNDOS)


def contagem_cobrar_hoje() -> int:
    return _contagens()[0]


def contagem_a_bloquear() -> int:
    """Contratos com 8 dias ou mais de atraso: hora de bloquear o aparelho (ação manual)."""
    return _contagens()[1]


def contagem_a_desbloquear() -> int:
    """Aparelhos bloqueados cujo cliente já regularizou: hora de liberar."""
    from apps.aparelhos.bloqueios import contar_a_desbloquear

    return sem_espera(f"aparelhos_a_desbloquear_n:{timezone.localdate().isoformat()}", contar_a_desbloquear, TTL_SEGUNDOS)


def contagem_promessas() -> int:
    """Promessas de pagamento para hoje ou já vencidas sem pagamento."""
    from .contatos import promessas_a_retornar

    return sem_espera(
        f"promessas_a_retornar_n:{timezone.localdate().isoformat()}", lambda: len(promessas_a_retornar()), TTL_SEGUNDOS
    )


def invalidar(**_kwargs) -> None:
    hoje = timezone.localdate().isoformat()
    for chave in (f"promessas_a_retornar_n:{hoje}", _chave(), f"aparelhos_a_desbloquear_n:{hoje}"):
        _apagar(chave)


TTL_WHATSAPP_SEGUNDOS = 60
TTL_WHATSAPP_AO_VIVO_SEGUNDOS = 3


def _consultar_whatsapp() -> str:
    from .whatsapp import WhatsAppErro, obter_status_conexao

    try:
        return obter_status_conexao()
    except WhatsAppErro:
        return "erro"


def status_whatsapp() -> str:
    """Estado da conexão do WhatsApp para o menu. **Nunca espera a rede**: vencido, mostra o último estado
    conhecido e renova em segundo plano (sem nenhum estado ainda, assume conectado até a resposta chegar).
    ``"erro"`` cobre tanto desconexão quanto falha de comunicação."""
    return sem_espera("whatsapp_status", _consultar_whatsapp, TTL_WHATSAPP_SEGUNDOS, padrao="open", bloquear_se_vazio=False)


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
        cache.set("whatsapp_status:antigo", estado, TTL_ANTIGO_SEGUNDOS)
    return estado


def contagem_sem_parcelas() -> int:
    """Contratos cujas parcelas geradas acabam antes de 30 dias (a rotina precisa gerar mais). Cache de 5 minutos."""
    import datetime

    from .proximas import contratos_sem_parcelas

    hoje = timezone.localdate()
    return sem_espera(
        f"contratos_sem_parcelas_n:{hoje.isoformat()}",
        lambda: len(contratos_sem_parcelas(hoje + datetime.timedelta(days=30))),
        300,
    )
