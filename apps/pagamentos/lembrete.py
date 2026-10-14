"""Lembrete diário para a Yslane, via WhatsApp (Fase 2, Modalidade A).

Decisão do Alisson (04/09): o canal do lembrete é **WhatsApp**. O envio agora
sai pela **Evolution API** (a mesma integração das cobranças ao cliente —
``apps.pagamentos.whatsapp``), que manda texto livre, sem template aprovado.

``montar_texto`` monta a agenda do dia e o resumo; ``enviar`` chama a Evolution
quando ``WHATSAPP_PROVIDER=evolution`` e só registra no log quando ``log``
(padrão). O resto do fluxo (job, texto, agenda) não muda.
"""

import datetime
import logging

from django.conf import settings

from .agenda import montar_agenda_do_dia

__all__ = ["montar_texto", "enviar", "enviar_lembrete_diario"]

logger = logging.getLogger("pagamentos.lembrete")


def _moeda(valor) -> str:
    return f"R$ {valor:.2f}".replace(".", ",")


def _extras(agenda: dict) -> str:
    """Promessas do dia, aparelhos a bloquear e as cobranças dos próximos 3 dias (só o que existir)."""
    from .contatos import promessas_a_retornar
    from .proximas import proximas_cobrancas

    hoje, partes = agenda["hoje"], []
    promessas = promessas_a_retornar(hoje)
    if promessas:
        partes += ["", "🤝 Promessas de pagamento (hoje ou vencidas):"]
        partes += [f"• {p.contato.contrato.cliente.nome} — prometeu até {p.contato.promessa_para:%d/%m}" for p in promessas]
    if agenda.get("n_bloqueio"):
        n = agenda["n_bloqueio"]
        partes += ["", f"🔒 {n} aparelho{'s' if n != 1 else ''} para bloquear (7+ dias de atraso)."]
    proximas = proximas_cobrancas(3, hoje)
    if proximas["quantidade"]:
        partes += ["", f"📅 Próximos 3 dias: {proximas['quantidade']} cobrança(s), {_moeda(proximas['total'])}."]
        partes += [f"• {g['data']:%d/%m}: {len(g['itens'])} — {_moeda(g['total'])}" for g in proximas["grupos"]]
    return "\n".join(partes)


def montar_texto_completo(agenda: dict) -> str:
    """O resumo do dia (`montar_texto`) mais os avisos: promessas, aparelhos a bloquear e próximos 3 dias."""
    texto = montar_texto(agenda)
    extras = _extras(agenda)
    return f"{texto}\n{extras}" if extras else texto


def montar_texto(agenda: dict) -> str:
    """Texto do resumo diário a partir de `agenda.montar_agenda_do_dia()`."""
    hoje = agenda["hoje"]
    linhas = agenda["linhas"]

    if not linhas:
        return f"Bom dia! Hoje ({hoje:%d/%m}) não tem ninguém pra cobrar. 🎉"

    plural_contrato = "s" if len(linhas) != 1 else ""
    plural_atraso = "s" if agenda["n_atraso"] != 1 else ""
    partes = [
        f"Bom dia! Cobrança de hoje ({hoje:%d/%m}) — {len(linhas)} contrato{plural_contrato}, "
        f"{agenda['n_atraso']} atrasado{plural_atraso}, "
        f"total previsto {_moeda(agenda['total_previsto'])}.",
        "",
    ]
    for linha in linhas:
        contrato = linha["contrato"]
        situacao = linha["situacao"]
        if linha["vence_hoje"]:
            tag = "vence hoje"
        else:
            tag = f"{situacao.dias_atraso}d de atraso"
            if situacao.alertar_bloqueio:
                tag += " ⚠ bloquear"
        valor = _moeda(linha["a_cobrar"]) if linha["parcela"] else "—"
        partes.append(f"• {contrato.cliente.nome} — {contrato.apelido} ({tag}) — {valor}")

    return "\n".join(partes)


def enviar(texto: str, numero: str | None = None) -> bool:
    """Envia o lembrete no WhatsApp da Yslane pela Evolution API.

    Com ``WHATSAPP_PROVIDER=log`` (padrão) só registra o texto no log e devolve
    ``True``. Com ``evolution``, chama a Evolution de verdade; falha de envio é
    logada e devolve ``False``. A assinatura é a mesma que o job diário usa.
    """
    destino = numero or getattr(settings, "YSLANE_WHATSAPP_NUMERO", "")
    if not destino:
        logger.warning(
            "YSLANE_WHATSAPP_NUMERO não configurado no .env — lembrete só logado."
        )
        logger.debug("[lembrete WhatsApp -> (sem número)]\n%s", texto)
        return True

    from .whatsapp import WhatsAppErro, enviar_mensagem, mascara_numero, numero_so_digitos

    alvo = mascara_numero(destino)
    try:
        resultado = enviar_mensagem(destinatario=numero_so_digitos(destino), texto=texto)
    except WhatsAppErro as exc:
        logger.error("Falha ao enviar o lembrete diário para %s: %s", alvo, exc)
        return False
    if resultado["simulado"]:
        logger.info("[lembrete WhatsApp -> %s] simulado (%d caractere(s))", alvo, len(texto))
    else:
        logger.info("[lembrete WhatsApp -> %s] enviado (id=%s)", alvo, resultado["id"])
    logger.debug("[lembrete WhatsApp -> %s]\n%s", destino, texto)
    return True


def enviar_lembrete_diario(hoje: datetime.date | None = None) -> str:
    """Monta a agenda do dia, gera o texto e chama `enviar`. Devolve o texto."""
    agenda = montar_agenda_do_dia(hoje=hoje)
    texto = montar_texto_completo(agenda)
    enviar(texto)
    return texto
