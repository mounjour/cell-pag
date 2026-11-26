"""Edição de uma parcela: data, valor e "valor a mais".

``valor_previsto`` continua sendo o que se cobra (mensagem, Pix e telas já leem dele); o ajuste fica em
``acrescimo`` para que, ao recalcular o contrato, o valor a mais não se perca: previsto = base + acrescimo.
"""

import datetime
from decimal import Decimal

from django.db import transaction

from .acordos import Aviso, _renovar_pix
from .models import Vencimento


class ParcelaInvalida(Exception):
    """Edição que não pode ser aplicada (a mensagem já é para o usuário)."""


def valor_base(vencimento: Vencimento) -> Decimal:
    """Valor da parcela sem o ajuste."""
    return vencimento.valor_previsto - vencimento.acrescimo


def motivo_para_nao_editar(vencimento: Vencimento) -> str:
    if vencimento.contrato.quitado:
        return "O contrato já está quitado."
    if vencimento.status == Vencimento.Status.PAGO:
        return "Esta parcela já está paga."
    return ""


@transaction.atomic
def editar_parcela(
    vencimento: Vencimento, *, data_vencimento: datetime.date, valor_base: Decimal,
    acrescimo: Decimal = Decimal("0.00"), motivo: str = "", autor=None,
) -> list[Aviso]:
    """Aplica data, valor base e ajuste. Levanta ``ParcelaInvalida``. Devolve avisos sobre o Pix."""
    vencimento = Vencimento.objects.select_for_update().select_related("contrato").get(pk=vencimento.pk)
    if texto := motivo_para_nao_editar(vencimento):
        raise ParcelaInvalida(texto)
    valor_base = valor_base.quantize(Decimal("0.01"))
    acrescimo = acrescimo.quantize(Decimal("0.01"))
    novo_previsto = valor_base + acrescimo
    if novo_previsto <= 0:
        raise ParcelaInvalida("O valor da parcela (com o ajuste) precisa ser maior que zero.")
    if novo_previsto < vencimento.valor_pago:
        raise ParcelaInvalida(
            f"A parcela já recebeu R$ {vencimento.valor_pago:.2f}; o valor não pode ficar abaixo disso.".replace(".", ",")
        )

    mudou_valor = novo_previsto != vencimento.valor_previsto
    mudou_data = data_vencimento != vencimento.data_vencimento
    if mudou_data:
        vencimento.data_original = vencimento.data_original or vencimento.data_vencimento
        vencimento.data_vencimento = data_vencimento
        vencimento.juros_abonado = Decimal("0.00")  # o juros recomeça a contar da nova data
    vencimento.valor_previsto = novo_previsto
    vencimento.acrescimo = acrescimo
    vencimento.acrescimo_motivo = motivo.strip()[:120] if acrescimo else ""
    vencimento.aplicar_valor_pago(vencimento.valor_pago, salvar=False)
    vencimento.save()
    avisos = []
    if mudou_data:
        avisos.extend(_reagendar_proximas_quinzenais(vencimento, autor))
    if mudou_valor or mudou_data:
        avisos.extend(_renovar_pix(vencimento, "Parcela editada", autor))
    return avisos


def _reagendar_proximas_quinzenais(vencimento: Vencimento, autor=None) -> list[Aviso]:
    """Reagenda a sequência quinzenal a partir de uma parcela cuja data mudou.

    A alteração passa a ser o novo marco do contrato, para que parcelas ainda não
    geradas também respeitem o intervalo de 15 dias. Parcelas já pagas ou que já
    receberam baixa mantêm o histórico registrado.
    """
    contrato = vencimento.contrato
    if contrato.estrutura != contrato.Estrutura.QUINZENAL or contrato.dias_cobranca_mes:
        return []

    contrato.primeira_cobranca = vencimento.data_vencimento - datetime.timedelta(days=15 * (vencimento.numero - 1))
    contrato.atualizar_data_prevista_quitacao(salvar=False)
    contrato.save(update_fields=["primeira_cobranca", "data_prevista_quitacao", "atualizado_em"])

    avisos = []
    posteriores = (
        Vencimento.objects.select_for_update()
        .filter(contrato=contrato, numero__gt=vencimento.numero, pagamentos__isnull=True)
        .exclude(status=Vencimento.Status.PAGO)
        .order_by("numero")
    )
    for posterior in posteriores:
        nova_data = contrato.data_da_parcela(posterior.numero)
        if posterior.data_vencimento == nova_data:
            continue
        posterior.data_original = posterior.data_original or posterior.data_vencimento
        posterior.data_vencimento = nova_data
        posterior.juros_abonado = Decimal("0.00")
        posterior.save(update_fields=["data_original", "data_vencimento", "juros_abonado", "atualizado_em"])
        avisos.extend(_renovar_pix(posterior, "Calendário quinzenal alterado", autor))
    return avisos


def _pix_desatualizado(venc) -> bool:
    """Pix estático aberto cujo valor (sem juros do atraso) ou data não bate mais com a parcela."""
    from django.conf import settings

    from .models import CobrancaCora

    if settings.PIX_MODO != "estatico":
        return False
    pix = CobrancaCora.objects.filter(vencimento=venc).exclude(
        status__in=(CobrancaCora.Status.PAGO, CobrancaCora.Status.CANCELADO)
    ).first()
    return pix is not None and (pix.data_vencimento != venc.data_vencimento or pix.valor - pix.juros != venc.saldo)


def ressincronizar_parcelas_em_aberto(contrato) -> int:
    """Depois de editar o contrato, leva valor e data novos às parcelas ainda sem baixa.

    Mantém o ``acrescimo`` de cada parcela e não mexe em parcela prorrogada em acordo
    (``data_original``) nem em parcela já paga ou com pagamento. Devolve quantas mudaram.
    """
    if contrato.quitado or contrato.valor_parcela is None:
        return 0
    mudadas = 0
    for venc in contrato.vencimentos.exclude(status=Vencimento.Status.PAGO).filter(pagamentos__isnull=True):
        novo_valor = contrato.valor_parcela + venc.acrescimo
        nova_data = venc.data_vencimento if venc.data_original else contrato.data_da_parcela(venc.numero)
        if novo_valor == venc.valor_previsto and nova_data == venc.data_vencimento:
            if _pix_desatualizado(venc):  # parcela certa, mas o código Pix guardado ficou com valor ou data antigos
                _renovar_pix(venc, "Contrato editado")
            continue
        venc.valor_previsto = novo_valor
        venc.data_vencimento = nova_data
        venc.save(update_fields=["valor_previsto", "data_vencimento", "atualizado_em"])
        _renovar_pix(venc, "Contrato editado")
        mudadas += 1
    return mudadas
