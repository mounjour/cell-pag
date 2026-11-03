"""Fila diária de cobrança direta aos clientes (Fase 6)."""

import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .agenda import montar_agenda_do_dia
from .models import Cobranca, CobrancaCora, ConfiguracaoCobranca
from .pix_cora import obter_ou_criar_cobranca
from .whatsapp import WhatsAppErro, enviar_imagem, enviar_mensagem, numero_so_digitos

logger = logging.getLogger("pagamentos.cobranca")


def _moeda(valor) -> str:
    return f"{valor:.2f}".replace(".", ",")


def _dias(n: int) -> str:
    return f"{n} dia" if n == 1 else f"{n} dias"


def _linha_da_parcela(p) -> str:
    """Uma linha por parcela: vencimento, atraso e valor **dela** (não do contrato)."""
    data = p.data_vencimento.strftime("%d/%m")
    if p.dias_atraso:
        situacao = f"venceu {data}, {_dias(p.dias_atraso)} de atraso"
    else:
        situacao = "cobrança hoje"
    linha = f"• *Parcela {p.numero}* ({situacao}): R$ {_moeda(p.saldo)}"
    if p.juros:
        linha += f" + R$ {_moeda(p.juros)} de juros"
    return linha


def _mensagem_varias_parcelas(base, parcelas, bloco_pix, *, alertar_bloqueio) -> str:
    """Cobrança de um contrato com mais de uma parcela em aberto.

    Lista cada parcela com o atraso próprio. O Pix fica vinculado à mais
    antiga e cobra o total: a soma dos saldos das parcelas vencidas **mais os
    juros** (não existe a opção de pagar só a parcela).
    """
    soma = sum((p.saldo for p in parcelas), Decimal("0.00"))
    juros = sum((p.juros for p in parcelas), Decimal("0.00"))
    mais_antiga = parcelas[0]
    partes = [
        f"Oi, {base['nome']}! 👋",
        f"O seu {base['aparelho']} tem {len(parcelas)} parcelas em aberto:",
        "\n".join(_linha_da_parcela(p) for p in parcelas),
        f"💰 *Total das parcelas: R$ {_moeda(soma)}*"
        + (f"\n➕ Juros pelo atraso: R$ {_moeda(juros)}\n✅ *Total a pagar: R$ {_moeda(soma + juros)}*" if juros else ""),
    ]
    if alertar_bloqueio:
        partes.append(
            f"⚠️ A parcela {mais_antiga.numero} já passou de {_dias(mais_antiga.dias_atraso)} de atraso: "
            "preciso que seja regularizada *hoje* para evitar o bloqueio do aparelho."
        )
    partes.append(
        f"Pra deixar tudo em dia, é só pagar o total — *R$ {_moeda(soma + juros)}*"
        + (" (parcelas + juros)" if juros else "")
        + " — no Pix abaixo.\n\n" + bloco_pix
    )
    partes.append("Depois é só me mandar o comprovante por aqui. Se já pagou, é só desconsiderar. 🙏")
    return "\n\n".join(partes)


def dados_da_mensagem(linha: dict, *, chave_pix=None) -> dict:
    contrato = linha["contrato"]
    situacao = linha["situacao"]
    vencimento = contrato.parcela_em_aberto()
    data_vencimento = vencimento.data_vencimento if vencimento else contrato.proximo_vencimento
    numero = vencimento.numero if vencimento else "-"
    chave_pix = chave_pix or settings.WHATSAPP_PIX_CHAVE or "a combinar"
    # O Pix (via Cora) cobra sempre o total: parcela + juros de atraso. O cliente
    # não tem a opção de pagar só a parcela, e o QR é refeito a cada dia de atraso
    # para acompanhar o juros. A mensagem mostra a conta e o total que o Pix pede.
    parcela = linha.get("parcela") or Decimal("0.00")
    juros = situacao.juros

    base = {
        "nome": contrato.cliente.nome,
        "aparelho": contrato.apelido,
        "numero": str(numero),
        "data": data_vencimento.strftime("%d/%m/%Y") if data_vencimento else "-",
        "dias": str(situacao.dias_atraso),
        "parcela": _moeda(parcela),
        "juros": _moeda(juros),
        "chave_pix": chave_pix,
    }
    # WhatsApp: *texto* é negrito e "\n" é quebra de linha. O código copia-e-cola
    # NÃO vai nesta mensagem: é longo, tem espaços no meio (nome do recebedor) e
    # o WhatsApp quebra a linha neles, o que atrapalha copiar. Ele segue sozinho
    # numa mensagem à parte (ver `processar_cobrancas`), que o cliente copia com
    # um toque. Um código Pix de verdade tem bem mais de 40 caracteres; abaixo
    # disso é a chave configurada (e-mail, telefone...) ou o "a combinar".
    base["codigo_pix"] = chave_pix if len(chave_pix) > 40 else None
    if base["codigo_pix"]:
        bloco_pix = "*Pix copia e cola:* copie o código da mensagem abaixo ⬇️"
    else:
        bloco_pix = f"*Chave Pix:* {chave_pix}"
    linha_valor = f"💰 *Parcela: R$ {base['parcela']}*"
    if juros:
        total = _moeda(parcela + juros)
        linha_valor += (
            f"\n➕ Juros pelo atraso: R$ {base['juros']}"
            f"\n✅ *Total a pagar: R$ {total}* (o Pix já vem com esse valor)"
        )
    parcelas = linha.get("parcelas") or []
    if len(parcelas) > 1:
        base["mensagem"] = _mensagem_varias_parcelas(
            base, parcelas, bloco_pix, alertar_bloqueio=situacao.alertar_bloqueio
        )
    elif situacao.alertar_bloqueio:
        base.update(
            mensagem=(
                f"Olá, {base['nome']}! 👋\n\n"
                f"A parcela {numero} do seu {base['aparelho']} está com "
                f"{base['dias']} dias de atraso.\n\n"
                f"⚠️ Preciso que seja regularizada *hoje* para evitar o bloqueio do aparelho.\n\n"
                f"{linha_valor}\n\n"
                f"{bloco_pix}\n\n"
                f"Me chama se precisar de ajuda pra resolver."
            ),
        )
    elif situacao.dias_atraso:
        base.update(
            mensagem=(
                f"Oi, {base['nome']}! 👋\n\n"
                f"A parcela {numero} do seu {base['aparelho']}, que venceu em {base['data']}, "
                f"está em aberto ({base['dias']} dia(s) de atraso).\n\n"
                f"{linha_valor}\n\n"
                f"{bloco_pix}\n\n"
                f"Assim que der, faz o Pix e me envia o comprovante. "
                f"Se já pagou, é só desconsiderar. 🙏"
            ),
        )
    else:
        base.update(
            mensagem=(
                f"Oi, {base['nome']}! 👋\n\n"
                f"Passando pra lembrar que hoje ({base['data']}) é a cobrança da parcela {numero} "
                f"do seu {base['aparelho']}.\n\n"
                f"{linha_valor}\n\n"
                f"{bloco_pix}\n\n"
                f"Depois é só me mandar o comprovante por aqui. 😊"
            ),
        )
    base["vencimento"] = vencimento
    return base


def _processar_linha(linha: dict, hoje: datetime.date, resultado: dict, somente_preparar: bool) -> None:
    """Prepara e envia a cobrança de uma linha da agenda (Pix, mensagem e registro), somando em ``resultado``."""
    dados_iniciais = dados_da_mensagem(linha)
    contrato = linha["contrato"]
    destinatario = numero_so_digitos(contrato.cliente.telefone_whatsapp)
    pix = (
        obter_ou_criar_cobranca(dados_iniciais["vencimento"], hoje=hoje)
        if dados_iniciais["vencimento"]
        else None
    )
    if pix and pix.status == CobrancaCora.Status.CANCELADO:
        # Alguém cancelou o Pix desta parcela: a cobrança automática dela está
        # suspensa. Não manda mensagem (o QR não vale mais) nem marca erro.
        resultado["ignoradas"] += 1
        return
    dados = dados_da_mensagem(
        linha,
        chave_pix=pix.pix_copia_e_cola if pix and pix.pix_copia_e_cola else None,
    )
    cobranca, criada = Cobranca.objects.get_or_create(
        contrato=contrato,
        data_alvo=hoje,
        canal=Cobranca.Canal.WHATSAPP,
        defaults={
            "vencimento": dados["vencimento"],
            "destinatario": destinatario,
            "mensagem": dados["mensagem"],
        },
    )
    if criada:
        resultado["preparadas"] += 1
    if settings.CORA_PROVIDER == "cora" and (pix is None or not pix.pix_copia_e_cola):
        cobranca.status = Cobranca.Status.ERRO
        cobranca.erro = pix.erro if pix else "Não foi possível vincular a cobrança a uma parcela."
        cobranca.save(update_fields=["status", "erro", "atualizado_em"])
        resultado["erros"] += 1
        return
    if cobranca.status in {
        Cobranca.Status.ENVIADO,
        Cobranca.Status.ENTREGUE,
        Cobranca.Status.LIDO,
        Cobranca.Status.CANCELADO,
        Cobranca.Status.APAGADO,
    }:
        resultado["ignoradas"] += 1
        return
    if somente_preparar:
        return

    try:
        if pix and pix.qr_code_url:
            resposta = enviar_imagem(
                destinatario=destinatario,
                imagem_url=pix.qr_code_url,
                legenda=dados["mensagem"],
            )
        else:
            resposta = enviar_mensagem(
                destinatario=destinatario,
                texto=dados["mensagem"],
            )
    except WhatsAppErro as exc:
        cobranca.status = Cobranca.Status.ERRO
        cobranca.erro = str(exc)
        cobranca.tentativas += 1
        cobranca.save(update_fields=["status", "erro", "tentativas", "atualizado_em"])
        resultado["erros"] += 1
        logger.exception("Falha na cobrança %s", cobranca.pk)
        return

    cobranca.tentativas += 1
    if resposta["simulado"]:
        cobranca.erro = "Modo de simulação: mensagem não enviada."
        resultado["simuladas"] += 1
    else:
        cobranca.status = Cobranca.Status.ENVIADO
        cobranca.id_externo = resposta["id"]
        cobranca.erro = ""
        cobranca.enviado_em = timezone.now()
        resultado["enviadas"] += 1
        # Copia-e-cola sozinho, por último: é a mensagem que o cliente toca e
        # segura para copiar. Se só ele falhar, a cobrança principal já saiu
        # (o cliente tem o QR) — registra o aviso sem marcar como erro, para
        # o retry não reenviar tudo de novo.
        if dados["codigo_pix"]:
            try:
                resposta_codigo = enviar_mensagem(destinatario=destinatario, texto=dados["codigo_pix"])
                cobranca.id_externo_codigo = resposta_codigo.get("id", "")
            except WhatsAppErro as exc:
                cobranca.erro = f"Copia-e-cola não enviado: {exc}"
                logger.warning("Copia-e-cola da cobrança %s não enviado: %s", cobranca.pk, exc)

    cobranca.save()


def processar_cobrancas(hoje: datetime.date | None = None, *, somente_preparar=False) -> dict:
    hoje = hoje or timezone.localdate()
    resultado = {"preparadas": 0, "enviadas": 0, "simuladas": 0, "erros": 0, "ignoradas": 0, "pausada": False}
    if ConfiguracaoCobranca.esta_pausada():
        # Chave geral desligada por alguém: nem Pix novo nem mensagem sai.
        resultado["pausada"] = True
        return resultado
    agenda = montar_agenda_do_dia(hoje=hoje)

    for linha in agenda["linhas"]:
        _processar_linha(linha, hoje, resultado, somente_preparar)

    return resultado


GRUPOS_DE_MENSAGENS = {
    "enviadas": [Cobranca.Status.ENVIADO, Cobranca.Status.ENTREGUE, Cobranca.Status.LIDO],
    "erro": [Cobranca.Status.ERRO],
    "pendentes": [Cobranca.Status.PENDENTE],
}


def mensagens_do_dia(dia: datetime.date, grupo: str = "") -> dict:
    """O que aconteceu com as mensagens de cobrança de um dia.

    Devolve as mensagens (filtradas por ``grupo``: enviadas, erro, pendentes ou todas), a contagem de cada grupo e,
    só para hoje, os contratos que estão na cobrança mas ainda não têm mensagem (a rotina não chegou neles)."""
    do_dia = list(Cobranca.objects.select_related("contrato__cliente").filter(data_alvo=dia).order_by("status", "contrato__cliente__nome"))
    contagem = {nome: sum(c.status in status for c in do_dia) for nome, status in GRUPOS_DE_MENSAGENS.items()}
    contagem["outras"] = len(do_dia) - sum(contagem.values())
    contagem["todas"] = len(do_dia)
    mensagens = [c for c in do_dia if c.status in GRUPOS_DE_MENSAGENS[grupo]] if grupo in GRUPOS_DE_MENSAGENS else do_dia
    sem_mensagem = []
    if dia == timezone.localdate() and grupo in ("", "pendentes"):
        com_mensagem = {c.contrato_id for c in do_dia}
        sem_mensagem = [linha for linha in montar_agenda_do_dia(hoje=dia)["linhas"] if linha["contrato"].pk not in com_mensagem]
    return {"mensagens": mensagens, "contagem": contagem, "sem_mensagem": sem_mensagem}


def enviar_agora(contrato, hoje: datetime.date | None = None) -> tuple[str, str]:
    """Manda agora a cobrança de hoje e devolve ``(nível, texto)`` para a tela ou o chat.

    Nível: ``success``, ``warning`` (simulação), ``info`` (já enviada) ou ``error`` (nada saiu; o texto diz o motivo)."""
    hoje = hoje or timezone.localdate()
    nome = contrato.cliente.nome
    if contrato.quitado:
        return "error", f"{nome}: contrato quitado, não há o que cobrar."
    ja_enviada = Cobranca.objects.filter(
        contrato=contrato, data_alvo=hoje, canal=Cobranca.Canal.WHATSAPP,
        status__in=[Cobranca.Status.ENVIADO, Cobranca.Status.ENTREGUE, Cobranca.Status.LIDO],
    ).exists()
    if ja_enviada:
        return "info", f"A cobrança de hoje de {nome} já foi enviada."
    resultado = enviar_cobranca_do_contrato(contrato, hoje)
    cobranca = resultado["cobranca"]
    if resultado["ignoradas"] and (cobranca is None or cobranca.status != Cobranca.Status.ENVIADO):
        return "error", f"Nada foi enviado a {nome}: a cobrança desta parcela está suspensa (Pix cancelado). Retome a cobrança no cliente."
    if cobranca is None:
        return "error", f"{nome} não está na cobrança de hoje (não está atrasado nem vence hoje); nada foi enviado."
    if cobranca.status == Cobranca.Status.ERRO:
        return "error", f"A mensagem para {nome} não saiu: {cobranca.erro or 'erro no envio'}"
    if resultado["simuladas"]:
        return "warning", f"Modo de simulação: a mensagem para {nome} NÃO foi enviada de verdade."
    return "success", f"Cobrança enviada no WhatsApp de {nome}."


def enviar_cobranca_do_contrato(contrato, hoje: datetime.date | None = None) -> dict:
    """Manda agora a cobrança de hoje de um contrato (a mesma mensagem e Pix da rotina). Não depende da pausa geral.

    Devolve o mesmo resumo da rotina; ``None`` em ``cobranca`` quando o contrato não está na cobrança de hoje."""
    hoje = hoje or timezone.localdate()
    resultado = {"preparadas": 0, "enviadas": 0, "simuladas": 0, "erros": 0, "ignoradas": 0, "pausada": False}
    linha = next((l for l in montar_agenda_do_dia(hoje=hoje)["linhas"] if l["contrato"].pk == contrato.pk), None)
    if linha is None:
        return {**resultado, "cobranca": None}
    # Mensagem do dia apagada ou cancelada (ex.: depois de um pagamento parcial) e o contrato ainda deve: manda outra.
    from .limpeza import reabrir_cobranca

    for antiga in Cobranca.objects.filter(
        contrato=contrato, data_alvo=hoje, canal=Cobranca.Canal.WHATSAPP,
        status__in=[Cobranca.Status.APAGADO, Cobranca.Status.CANCELADO],
    ):
        reabrir_cobranca(antiga)
    _processar_linha(linha, hoje, resultado, False)
    resultado["cobranca"] = Cobranca.objects.filter(contrato=contrato, data_alvo=hoje, canal=Cobranca.Canal.WHATSAPP).first()
    return resultado
