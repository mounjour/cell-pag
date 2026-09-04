"""Fila diária de cobrança direta aos clientes (Fase 6)."""

import datetime
import logging

from django.conf import settings
from django.utils import timezone

from .agenda import montar_agenda_do_dia
from .models import Cobranca
from .pix_cora import obter_ou_criar_pix
from .whatsapp import WhatsAppErro, enviar_template, numero_so_digitos

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
    valor = linha["a_cobrar"]

    base = {
        "nome": contrato.cliente.nome,
        "aparelho": contrato.apelido,
        "numero": str(numero),
        "data": data_vencimento.strftime("%d/%m/%Y") if data_vencimento else "-",
        "dias": str(situacao.dias_atraso),
        "valor": _moeda(valor),
        "chave_pix": chave_pix,
    }
    if situacao.alertar_bloqueio:
        base.update(
            template=settings.WHATSAPP_TEMPLATE_BLOQUEIO,
            parametros=[base["nome"], base["numero"], base["aparelho"], base["dias"], base["valor"], chave_pix],
            mensagem=(
                f"Oi, {base['nome']}! A parcela {numero} do seu {base['aparelho']} está "
                f"com {base['dias']} dias de atraso. Preciso que seja regularizada hoje para "
                f"evitar o bloqueio do aparelho. Valor atualizado: R$ {base['valor']} - "
                f"Pix ({chave_pix}). Me chama se precisar de ajuda pra resolver."
            ),
        )
    elif situacao.dias_atraso:
        base.update(
            template=settings.WHATSAPP_TEMPLATE_ATRASO,
            parametros=[base["nome"], base["numero"], base["aparelho"], base["data"], base["dias"], base["valor"], chave_pix],
            mensagem=(
                f"Oi, {base['nome']}! A parcela {numero} do seu {base['aparelho']}, que venceu "
                f"em {base['data']}, está em aberto ({base['dias']} dia(s) de atraso). "
                f"O valor atualizado está em R$ {base['valor']}. Assim que der, faz o Pix "
                f"({chave_pix}) e me envia o comprovante. Se já pagou, é só desconsiderar."
            ),
        )
    else:
        base.update(
            template=settings.WHATSAPP_TEMPLATE_VENCIMENTO,
            parametros=[base["nome"], base["data"], base["numero"], base["aparelho"], base["valor"], chave_pix],
            mensagem=(
                f"Oi, {base['nome']}! Passando pra lembrar que hoje ({base['data']}) vence a "
                f"parcela {numero} do seu {base['aparelho']}, no valor de R$ {base['valor']}. "
                f"Você pode pagar via Pix ({chave_pix}) e me mandar o comprovante por aqui."
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
            obter_ou_criar_pix(dados_iniciais["vencimento"], hoje=hoje)
            if dados_iniciais["vencimento"]
            else None
        )
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
            resposta = enviar_template(
                destinatario=destinatario,
                template=dados["template"],
                parametros=dados["parametros"],
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
        cobranca.save()

    return resultado
