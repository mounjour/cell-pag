"""Comprovantes que o cliente manda por WhatsApp e a confirmação de pagamento.

Uma imagem ou PDF **não prova** que o Pix foi feito (qualquer foto passa por
comprovante); quem prova é a Cora. Por isso o arquivo recebido é só um *aviso*:

1. o sistema reconhece o cliente pelo número, acha a parcela em aberto e
   consulta a Cora;
2. se o Pix ainda não caiu, o cliente recebe uma resposta automática e o
   financeiro vê o alerta no painel Pix (para conferir ou descartar);
3. quando o Pix cai na Cora e o sistema dá a baixa, o cliente recebe a
   confirmação por WhatsApp (isto vale para todo Pix confirmado, com ou sem
   comprovante) e os avisos pendentes daquela parcela são resolvidos.

O arquivo em si não é guardado — só o fato de que chegou.
"""

import datetime
import logging
import re

from django.db import transaction
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato

from . import cora_api
from .models import CobrancaCora, ComprovanteRecebido
from .whatsapp import WhatsAppErro, enviar_mensagem, numero_so_digitos

logger = logging.getLogger("pagamentos.comprovantes")

# Não responde de novo ao mesmo cliente dentro deste intervalo (evita spam se ele
# mandar várias fotos seguidas).
INTERVALO_ENTRE_RESPOSTAS = datetime.timedelta(hours=6)


# ── Reconhecer quem mandou ────────────────────────────────────────────────────

def _variantes_do_numero(digitos: str) -> set[str]:
    """Formas E.164 possíveis: o WhatsApp às vezes omite o 9 dos celulares do Brasil."""
    variantes = {f"+{digitos}"}
    if digitos.startswith("55") and len(digitos) == 13 and digitos[4] == "9":
        variantes.add(f"+{digitos[:4]}{digitos[5:]}")  # sem o 9
    elif digitos.startswith("55") and len(digitos) == 12:
        variantes.add(f"+{digitos[:4]}9{digitos[4:]}")  # com o 9
    return variantes


def _jid_de_pessoa(key: dict) -> str:
    """Devolve o número (só dígitos) de uma conversa individual, ou '' (grupos e
    identificadores anônimos "@lid" sem número são ignorados)."""
    for candidato in (key.get("remoteJid"), key.get("remoteJidAlt"), key.get("senderPn")):
        if isinstance(candidato, str) and candidato.endswith("@s.whatsapp.net"):
            return re.sub(r"\D", "", candidato.split("@")[0])
    return ""


def achar_cliente(digitos: str) -> Cliente | None:
    if not digitos:
        return None
    return Cliente.objects.filter(
        telefone_whatsapp__in=_variantes_do_numero(digitos), ativo=True
    ).first()


def parcela_em_aberto_do_cliente(cliente: Cliente):
    """A parcela em aberto mais antiga entre os contratos ativos do cliente."""
    abertas = []
    for contrato in cliente.contratos.exclude(status=Contrato.Status.QUITADO):
        parcela = contrato.parcela_em_aberto()
        if parcela is not None:
            abertas.append(parcela)
    return min(abertas, key=lambda v: v.data_vencimento) if abertas else None


# ── Mensagem recebida (webhook) ───────────────────────────────────────────────

def _arquivo_da_mensagem(mensagem: dict):
    """(tipo, nome, legenda) se a mensagem for imagem ou PDF; senão None."""
    imagem = mensagem.get("imageMessage")
    if isinstance(imagem, dict):
        return ComprovanteRecebido.Tipo.IMAGEM, "", imagem.get("caption") or ""
    documento = mensagem.get("documentMessage")
    if documento is None:  # legenda em documento vem aninhada
        documento = (mensagem.get("documentWithCaptionMessage") or {}).get("message", {}).get("documentMessage")
    if isinstance(documento, dict):
        mimetype = str(documento.get("mimetype", "")).lower()
        if mimetype == "application/pdf" or mimetype.startswith("image/"):
            return (
                ComprovanteRecebido.Tipo.DOCUMENTO,
                str(documento.get("fileName", ""))[:200],
                documento.get("caption") or "",
            )
    return None


def processar_mensagem_recebida(dado: dict) -> ComprovanteRecebido | None:
    """Trata uma mensagem que o cliente enviou. Só interessa imagem/PDF de um
    cliente conhecido; o resto (texto, áudio, figurinha, desconhecidos) é ignorado."""
    if not isinstance(dado, dict):
        return None
    chave = dado.get("key") or {}
    if chave.get("fromMe") or not chave.get("id"):
        return None
    arquivo = _arquivo_da_mensagem(dado.get("message") or {})
    if arquivo is None:
        return None
    cliente = achar_cliente(_jid_de_pessoa(chave))
    if cliente is None:
        logger.info("Arquivo recebido de número que não é de cliente; ignorado.")
        return None

    tipo, nome, legenda = arquivo
    comprovante, criado = ComprovanteRecebido.objects.get_or_create(
        id_externo=chave["id"],
        defaults={
            "cliente": cliente,
            "vencimento": parcela_em_aberto_do_cliente(cliente),
            "tipo": tipo,
            "nome_arquivo": nome,
            "legenda": legenda[:500],
        },
    )
    if not criado:  # a Evolution repete avisos: não processa duas vezes
        return comprovante

    conferir_na_cora(comprovante)
    comprovante.refresh_from_db()
    if comprovante.status == ComprovanteRecebido.Status.AGUARDANDO:
        _avisar_cliente_que_ainda_nao_caiu(comprovante)
    return comprovante


def conferir_na_cora(comprovante: ComprovanteRecebido) -> bool:
    """Consulta a Cora sobre a parcela. Se o Pix já foi pago, a baixa (e a
    confirmação ao cliente) acontecem por ``ao_confirmar_pix``. Devolve se
    a consulta foi feita."""
    from .pix_cora import sincronizar_cobranca

    if comprovante.vencimento_id is None:
        return False
    pix = CobrancaCora.objects.filter(vencimento_id=comprovante.vencimento_id).first()
    if pix is None or not pix.cora_id:
        return False
    try:
        sincronizar_cobranca(pix)
    except cora_api.CoraErro as exc:
        logger.warning("Não consegui consultar a Cora para o comprovante %s: %s", comprovante.pk, exc)
        return False
    return True


def _primeiro_nome(cliente: Cliente) -> str:
    return (cliente.nome or "").split()[0].title() if cliente.nome else ""


def _avisar_cliente_que_ainda_nao_caiu(comprovante: ComprovanteRecebido) -> None:
    recente = timezone.now() - INTERVALO_ENTRE_RESPOSTAS
    ja_respondido = ComprovanteRecebido.objects.filter(
        cliente=comprovante.cliente, resposta_enviada_em__gte=recente
    ).exists()
    if ja_respondido:
        return
    texto = (
        f"Olá, {_primeiro_nome(comprovante.cliente)}! Recebemos o seu comprovante. "
        "Ainda não identificamos esse Pix na nossa conta — pode levar alguns minutos. "
        "Assim que ele cair, avisamos por aqui. Se precisar, é só responder esta mensagem."
    )
    try:
        resposta = enviar_mensagem(
            destinatario=numero_so_digitos(comprovante.cliente.telefone_whatsapp), texto=texto
        )
    except WhatsAppErro as exc:
        logger.warning("Resposta ao comprovante %s não enviada: %s", comprovante.pk, exc)
        return
    if not resposta.get("simulado"):
        comprovante.resposta_enviada_em = timezone.now()
        comprovante.save(update_fields=["resposta_enviada_em"])


# ── Pix confirmado pela Cora ──────────────────────────────────────────────────

def ao_confirmar_pix(cobranca: CobrancaCora, pagamento) -> None:
    """Chamado logo depois da baixa automática de um Pix: resolve os avisos de
    comprovante da parcela e manda a confirmação ao cliente (uma vez só)."""
    ComprovanteRecebido.objects.filter(
        vencimento_id=cobranca.vencimento_id, status=ComprovanteRecebido.Status.AGUARDANDO
    ).update(status=ComprovanteRecebido.Status.CONFIRMADO, resolvido_em=timezone.now())
    # Depois do commit: nunca fazer chamada de rede dentro da transação da baixa.
    transaction.on_commit(lambda: enviar_confirmacao(cobranca.pk))


def enviar_confirmacao(cobranca_id: int) -> bool:
    cobranca = (
        CobrancaCora.objects.select_related("vencimento__contrato__cliente").filter(pk=cobranca_id).first()
    )
    if cobranca is None or cobranca.confirmacao_enviada_em is not None:
        return False
    vencimento = cobranca.vencimento
    contrato = vencimento.contrato
    valor = f"{cobranca.total_pago:.2f}".replace(".", ",")
    detalhe = ""
    if cobranca.juros:
        juros = min(cobranca.juros, cobranca.total_pago)
        parcela = f"{cobranca.total_pago - juros:.2f}".replace(".", ",")
        detalhe = f", sendo R$ {parcela} de parcela e R$ {f'{juros:.2f}'.replace('.', ',')} de juros"
    texto = (
        f"Olá, {_primeiro_nome(contrato.cliente)}! Recebemos o seu pagamento de R$ {valor}{detalhe} "
        f"(parcela {vencimento.numero} — {contrato.apelido}). Obrigado!"
    )
    try:
        resposta = enviar_mensagem(
            destinatario=numero_so_digitos(contrato.cliente.telefone_whatsapp), texto=texto
        )
    except WhatsAppErro as exc:
        logger.warning("Confirmação do Pix %s não enviada: %s", cobranca.pk, exc)
        return False
    if resposta.get("simulado"):
        return False
    cobranca.confirmacao_enviada_em = timezone.now()
    cobranca.save(update_fields=["confirmacao_enviada_em", "atualizado_em"])
    return True
