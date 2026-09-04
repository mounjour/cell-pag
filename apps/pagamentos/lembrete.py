"""Lembrete diário para a Yslane, via WhatsApp (Fase 2, Modalidade A).

Decisão do Alisson (04/09): o canal do lembrete é **WhatsApp** (a ideia
anterior de Telegram/e-mail — seção 13 do plano — não vale mais). Só que o
projeto ainda não tem nenhuma integração de envio: o WhatsApp oficial (Cloud
API, direto na Meta ou via BSP como 360dialog/Zenvia) só estava previsto para
a Fase 6, e exige conta Business verificada + template de mensagem aprovado
pela Meta — não é só mandar texto livre.

**Decisão (Alisson, 04/09): "deixar pronto, sem conta ainda".** `montar_texto`
e `enviar_lembrete_diario` já fazem o trabalho de verdade (montam a agenda do
dia e o texto do resumo); `enviar` é um **stub** — só registra no log o que
seria mandado e devolve sucesso. Quando a conta Business existir, troca-se só
o corpo de `enviar` pela chamada ao provedor escolhido; o resto do fluxo (job,
texto, agenda) não muda.
"""

import datetime
import logging

from django.conf import settings

from .agenda import montar_agenda_do_dia

__all__ = ["montar_texto", "enviar", "enviar_lembrete_diario"]

logger = logging.getLogger("pagamentos.lembrete")


def _moeda(valor) -> str:
    return f"R$ {valor:.2f}".replace(".", ",")


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
    """Envia (por ora, apenas registra) o lembrete no WhatsApp da Yslane.

    **Stub** — sem conta WhatsApp Business ainda (Alisson, 04/09), não chama
    nenhuma API. Loga o texto e devolve ``True`` (como se tivesse entrado na
    fila de envio). Trocar o corpo desta função pela chamada ao provedor
    (Cloud API/BSP) quando a conta existir — a assinatura já é a que o job usa.
    """
    destino = numero or getattr(settings, "YSLANE_WHATSAPP_NUMERO", "")
    if not destino:
        logger.warning(
            "YSLANE_WHATSAPP_NUMERO não configurado no .env — lembrete só logado."
        )
    logger.info("[lembrete WhatsApp -> %s]\n%s", destino or "(sem número)", texto)
    return True


def enviar_lembrete_diario(hoje: datetime.date | None = None) -> str:
    """Monta a agenda do dia, gera o texto e chama `enviar`. Devolve o texto."""
    agenda = montar_agenda_do_dia(hoje=hoje)
    texto = montar_texto(agenda)
    enviar(texto)
    return texto
