"""Prévia de baixa, sem gravar pagamentos ou alterar parcelas."""

from decimal import Decimal

from .models import Vencimento


def moeda(valor):
    return f"R$ {valor:.2f}".replace(".", ",")


def prever_pagamento(contrato, vencimento, valor, juros=Decimal("0.00")):
    linhas = [f"Recebimento: {moeda(valor)} de parcelas + {moeda(juros)} de juros = {moeda(valor + juros)}."]
    restante = vencimento.saldo - valor
    if restante > 0:
        linhas.append(
            f"Parcela {vencimento.numero}: pagamento parcial; faltam {moeda(restante)}, que continuam sendo cobrados "
            "nesta parcela (com o juros do atraso) até quitar."
        )
        linhas.append("Os juros ficam registrados à parte. Prévia com os saldos atuais; nenhum pagamento foi salvo.")
        return "\n".join(linhas)
    linhas.append(f"Parcela {vencimento.numero}: ficará paga.")
    seguintes = contrato.vencimentos.filter(numero__gt=vencimento.numero).exclude(
        status=Vencimento.Status.PAGO,
    ).order_by("numero")
    for alvo in seguintes:
        if not restante:
            break
        novo_valor = alvo.valor_previsto + restante
        abatimento = min(-restante, alvo.valor_previsto)
        linhas.append(f"Parcela {alvo.numero}: abatimento de {moeda(abatimento)}; previsto: {moeda(max(novo_valor, Decimal('0.00')))}.")
        restante = min(novo_valor, Decimal("0.00"))
    if restante:
        linhas.append(f"Sem próxima parcela disponível: {moeda(abs(restante))} ficará como crédito no contrato, para as próximas parcelas geradas.")
    linhas.append("Os juros ficam registrados à parte. Prévia com os saldos atuais; nenhum pagamento foi salvo.")
    return "\n".join(linhas)
