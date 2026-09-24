"""Fila diária de cobrança direta aos clientes (Fase 6)."""

import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .agenda import montar_agenda_do_dia
from .models import Cobranca, CobrancaCora
from .pix_cora import obter_ou_criar_cobranca
from .whatsapp import WhatsAppErro, enviar_imagem, enviar_mensagem, numero_so_digitos

logger = logging.getLogger("pagamentos.cobranca")


def _moeda(valor) -> str:
    return f"{valor:.2f}".replace(".", ",")


def dados_da_mensagem(linha: dict, *, chave_pix=None) -> dict:
    contrato = linha["contrato"]
    situacao = linha["situacao"]
    vencimento = contrato.parcela_em_aberto()
    data_vencimento = vencimento.data_vencimento if vencimento else contrato.proximo_vencimento
    numero = vencimento.numero if vencimento else "-"
    chave_pix = chave_pix or settings.WHATSAPP_PIX_CHAVE or "a combinar"
    # O Pix automático (via Cora) cobra só o saldo da parcela — nunca o
    # juros (decisão do Alisson, 18/09: juros fica de cobrança manual, já
    # que o valor muda todo dia de atraso e a Cora não recria a cobrança
    # sozinha). A mensagem não pode prometer um "valor atualizado" maior do
    # que o Pix realmente vai pedir — por isso os dois valores vêm
    # separados aqui, com o juros marcado como "a combinar".
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
        linha_valor += (
            f"\n➕ Juros pelo atraso: R$ {base['juros']} (isso a gente combina à parte)"
        )
    if situacao.alertar_bloqueio:
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
                f"Passando pra lembrar que hoje ({base['data']}) vence a parcela {numero} "
                f"do seu {base['aparelho']}.\n\n"
                f"{linha_valor}\n\n"
                f"{bloco_pix}\n\n"
                f"Depois é só me mandar o comprovante por aqui. 😊"
            ),
        )
    base["vencimento"] = vencimento
    return base


def processar_cobrancas(hoje: datetime.date | None = None, *, somente_preparar=False) -> dict:
    hoje = hoje or timezone.localdate()
    agenda = montar_agenda_do_dia(hoje=hoje)
    resultado = {"preparadas": 0, "enviadas": 0, "simuladas": 0, "erros": 0, "ignoradas": 0}

    for linha in agenda["linhas"]:
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
            continue
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
            continue
        if cobranca.status in {Cobranca.Status.ENVIADO, Cobranca.Status.ENTREGUE, Cobranca.Status.LIDO}:
            resultado["ignoradas"] += 1
            continue
        if somente_preparar:
            continue

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
            continue

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
                    enviar_mensagem(destinatario=destinatario, texto=dados["codigo_pix"])
                except WhatsAppErro as exc:
                    cobranca.erro = f"Copia-e-cola não enviado: {exc}"
                    logger.warning("Copia-e-cola da cobrança %s não enviado: %s", cobranca.pk, exc)

        cobranca.save()

    return resultado
