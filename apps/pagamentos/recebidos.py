"""Pix recebidos direto na Cora (transferência comum) que ainda não viraram baixa no sistema.

O webhook da Cora só avisa dos QR codes gerados pelo sistema. Quem paga pela chave Pix cai no extrato,
sem parcela ligada. Aqui o extrato é lido (só leitura), cada entrada vira um `RecebimentoCora` e o sistema
sugere de quem é (pelo CPF e, na falta dele, pelo nome) para a equipe registrar o pagamento com um clique.
"""

import datetime
import logging
import re
import unicodedata

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import cora_api
from .models import CobrancaCora, Pagamento, RecebimentoCora

logger = logging.getLogger("pagamentos.recebidos")

PREFIXO_BAIXA_EXTRATO = "Baixa automática pelo extrato da Cora"
#: Só entradas recentes recebem baixa sozinhas; as mais antigas ficam para a equipe conferir.
JANELA_BAIXA_AUTOMATICA = datetime.timedelta(hours=36)

_CHAVE_SINCRONIA = "recebidos_cora_sincronizado"
_TTL_SINCRONIA = 300  # no máximo uma consulta ao extrato a cada 5 minutos


def sincronizar(dias: int = 30, forcar: bool = False) -> str:
    """Traz as entradas Pix do extrato para o banco. Devolve o texto do erro ("" quando deu certo)."""
    if settings.CORA_PROVIDER != "cora":
        return ""
    if not forcar and cache.get(_CHAVE_SINCRONIA):
        return ""
    hoje = timezone.localdate()
    try:
        entradas = cora_api.listar_extrato(hoje - datetime.timedelta(days=dias), hoje + datetime.timedelta(days=1))
    except cora_api.CoraErro as exc:
        return f"Não consegui consultar o extrato da Cora agora: {exc}"

    existentes = set(RecebimentoCora.objects.values_list("entrada_id", flat=True))
    pagos = list(CobrancaCora.objects.filter(status=CobrancaCora.Status.PAGO, pago_em__isnull=False)
                 .values_list("total_pago", "pago_em"))
    for entrada in entradas:
        if entrada["id"] in existentes or entrada["tipo"] != "PIX":
            continue
        # Pagamento de um QR do próprio sistema já tem baixa pelo webhook: não entra na lista.
        de_fatura = any(
            total == entrada["valor"] and abs((pago_em - entrada["recebido_em"]).total_seconds()) < 2 * 86400
            for total, pago_em in pagos
        )
        recebimento = RecebimentoCora.objects.create(
            entrada_id=entrada["id"], valor=entrada["valor"], recebido_em=entrada["recebido_em"],
            tipo=entrada["tipo"], nome=entrada["nome"], documento=entrada["documento"],
            situacao=RecebimentoCora.Situacao.VINCULADO if de_fatura else RecebimentoCora.Situacao.NOVO,
            tratado_em=timezone.now() if de_fatura else None,
        )
        if not de_fatura:
            _tratar_entrada_nova(recebimento)
    cache.set(_CHAVE_SINCRONIA, True, _TTL_SINCRONIA)
    return ""


def _tratar_entrada_nova(recebimento: RecebimentoCora) -> None:
    """Entrada nova: se já foi registrada à mão, só liga; se for recente e clara, dá a baixa sozinha."""
    try:
        registrado = _pagamento_ja_registrado(recebimento)
        if registrado is not None:
            vincular(recebimento.pk, registrado, None)
        elif timezone.now() - recebimento.recebido_em <= JANELA_BAIXA_AUTOMATICA:
            baixar_automaticamente(recebimento)
    except Exception:  # uma entrada com problema não pode travar as outras
        logger.exception("Falha ao tratar a entrada %s do extrato", recebimento.entrada_id)


def _pagamento_ja_registrado(recebimento: RecebimentoCora):
    """Pagamento Pix do mesmo CPF, no mesmo dia e com o mesmo total (parcela + juros): foi registrado à mão."""
    if not recebimento.documento:
        return None
    dia = timezone.localtime(recebimento.recebido_em).date()
    candidatos = Pagamento.objects.filter(
        contrato__cliente__cpf=recebimento.documento, data_pagamento=dia, forma=Pagamento.Forma.PIX,
    ).exclude(recebimentos_cora__isnull=False)
    return next((p for p in candidatos if p.valor_pago + p.juros_pago == recebimento.valor), None)


def estornar_liberando_extrato(pagamento) -> bool:
    """Estorna a baixa e devolve o Pix do extrato para \"A registrar\" (senão sumiria da lista sem ter pagamento).

    Devolve se a baixa havia transportado saldo para parcelas seguintes."""
    RecebimentoCora.objects.filter(pagamento=pagamento).update(
        situacao=RecebimentoCora.Situacao.NOVO, pagamento=None, tratado_em=None, tratado_por=None,
    )
    return bool(pagamento.estornar())


def ligar_entrada_ao_pagamento(pagamento, usuario):
    """Pagamento Pix registrado à mão (tela ou chat) depois de a entrada já estar na lista: liga as duas.

    Só liga quando é inequívoco: mesmo CPF, mesmo dia, mesmo total (parcela + juros) e uma única entrada."""
    cpf = pagamento.contrato.cliente.cpf
    if pagamento.forma != Pagamento.Forma.PIX or not cpf:
        return None
    candidatos = [
        r for r in RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.NOVO, documento=cpf, valor=pagamento.valor_pago + pagamento.juros_pago)
        if timezone.localtime(r.recebido_em).date() == pagamento.data_pagamento
    ]
    if len(candidatos) != 1:
        return None
    vincular(candidatos[0].pk, pagamento, usuario)
    return candidatos[0]


def baixar_automaticamente(recebimento: RecebimentoCora) -> Pagamento | None:
    """Dá a baixa quando o CPF de quem pagou é de um cliente e o valor cabe em **uma só** parcela em aberto.

    O valor precisa estar entre a parcela (principal) e parcela + juros do dia do pagamento: assim quem pagou o
    código de ontem (juros menor) também é reconhecido. Se mais de um contrato casar, ou nenhum, a entrada fica
    na lista para a equipe decidir.
    """
    from apps.clientes.models import Cliente

    from .comprovantes import ao_confirmar_pix
    from .limpeza import encerrar_cobranca_automatica
    from .pix_cora import composicao_do_pix

    if not recebimento.documento:
        return None
    dia = timezone.localtime(recebimento.recebido_em).date()
    candidatos = []
    for cliente in Cliente.objects.filter(cpf=recebimento.documento, ativo=True):
        for contrato in cliente.contratos.exclude(status="quitado"):
            parcela = (
                contrato.vencimentos.exclude(status="pago").exclude(pagamentos__isnull=False).order_by("numero").first()
            )
            if parcela is None:
                continue
            principal, juros = composicao_do_pix(parcela, dia)
            if principal > 0 and principal <= recebimento.valor <= principal + juros:
                candidatos.append((contrato, parcela, principal))
    if len(candidatos) != 1:
        return None

    contrato, parcela, principal = candidatos[0]
    with transaction.atomic():
        pagamento = Pagamento(
            contrato=contrato, vencimento=parcela, data_pagamento=dia, valor_pago=principal,
            juros_pago=recebimento.valor - principal, forma=Pagamento.Forma.PIX,
            observacao=f"{PREFIXO_BAIXA_EXTRATO} ({recebimento.entrada_id}).",
        )
        pagamento.registrar()
        vincular(recebimento.pk, pagamento, None)
        encerrar_cobranca_automatica(pagamento)
        pix = CobrancaCora.objects.filter(vencimento=parcela).first()
        if pix is not None:
            pix.total_pago, pix.pago_em, pix.status = recebimento.valor, recebimento.recebido_em, CobrancaCora.Status.PAGO
            pix.juros = min(pix.juros, recebimento.valor)
            pix.save()
            ao_confirmar_pix(pix, pagamento)
    return pagamento


def _normaliza(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return [parte for parte in re.split(r"[^a-z0-9]+", sem_acento) if len(parte) > 2]


def sugestoes(recebimento: RecebimentoCora) -> list[dict]:
    """Clientes prováveis (CPF igual ao de quem pagou; senão, o nome do cliente está no nome do remetente)."""
    from apps.clientes.models import Cliente

    ativos = Cliente.objects.filter(ativo=True)
    por_cpf = list(ativos.filter(cpf=recebimento.documento)) if recebimento.documento else []
    if por_cpf:
        candidatos, motivo = por_cpf, "mesmo CPF"
    else:
        partes = set(_normaliza(recebimento.nome))
        candidatos = [c for c in ativos if (nome := set(_normaliza(c.nome))) and nome <= partes][:3]
        motivo = "mesmo nome"
    resultado = []
    for cliente in candidatos:
        contratos = [
            (contrato, contrato.parcela_em_aberto())
            for contrato in cliente.contratos.exclude(status="quitado").select_related("cliente")
        ]
        resultado.append({"cliente": cliente, "motivo": motivo, "contratos": [c for c in contratos if c[1] is not None]})
    return resultado


def painel() -> dict:
    a_registrar = list(RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.NOVO))
    for item in a_registrar:
        item.sugestoes = sugestoes(item)
    tratados = RecebimentoCora.objects.exclude(situacao=RecebimentoCora.Situacao.NOVO).select_related("tratado_por")[:10]
    return {"a_registrar": a_registrar, "tratados": tratados}


def vincular(recebimento_id, pagamento, usuario) -> None:
    """Marca a entrada do extrato como registrada e a liga ao pagamento criado."""
    if not recebimento_id:
        return
    RecebimentoCora.objects.filter(pk=recebimento_id, situacao=RecebimentoCora.Situacao.NOVO).update(
        situacao=RecebimentoCora.Situacao.VINCULADO, pagamento=pagamento, tratado_em=timezone.now(),
        tratado_por=usuario,
    )


def ignorar(recebimento_id, usuario) -> bool:
    return bool(RecebimentoCora.objects.filter(pk=recebimento_id, situacao=RecebimentoCora.Situacao.NOVO).update(
        situacao=RecebimentoCora.Situacao.IGNORADO, tratado_em=timezone.now(), tratado_por=usuario,
    ))
