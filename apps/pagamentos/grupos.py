"""Grupos do WhatsApp que o sistema conhece pelas mensagens que chegam (a lista da Evolution pode vir incompleta)."""

import logging

from django.db.models import F
from django.utils import timezone

from .models import GrupoWhatsApp
from .whatsapp import WhatsAppErro, _chamar_evolution_get

logger = logging.getLogger("pagamentos.grupos")


def registrar_grupo_visto(dado) -> bool:
    """Se a mensagem do webhook veio de um grupo, guarda o identificador dele (nunca o conteúdo). Devolve se era de grupo."""
    chave = dado.get("key") if isinstance(dado, dict) else None
    jid = chave.get("remoteJid") if isinstance(chave, dict) else None
    if not (isinstance(jid, str) and jid.endswith("@g.us")):
        return False
    agora = timezone.now()
    if not GrupoWhatsApp.objects.filter(jid=jid).update(visto_em=agora, mensagens=F("mensagens") + 1):
        GrupoWhatsApp.objects.get_or_create(jid=jid, defaults={"visto_em": agora})
    return True


def completar_nomes(limite: int = 8) -> None:
    """Pergunta à Evolution o nome dos grupos vistos que ainda não têm (``GET /group/findGroupInfos``). Falha em silêncio."""
    for grupo in GrupoWhatsApp.objects.filter(nome="")[:limite]:
        try:
            dados = _chamar_evolution_get("/group/findGroupInfos", {"groupJid": grupo.jid})
        except WhatsAppErro as exc:
            logger.info("Não consegui o nome do grupo %s: %s", grupo.jid[-8:], exc)
            continue
        nome = str(dados.get("subject") or "")[:200] if isinstance(dados, dict) else ""
        if nome:
            grupo.nome = nome
            grupo.participantes = int(dados.get("size") or 0) or None
            grupo.save(update_fields=["nome", "participantes"])
