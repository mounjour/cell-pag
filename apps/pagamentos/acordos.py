"""Acordos com o cliente sobre uma parcela atrasada: perdoar juros ou marcar uma nova data.

O efeito vai direto na parcela (``Vencimento``), então a mensagem, o Pix e as telas já cobram o valor
combinado, sem nenhum caminho paralelo:

* **Perdoar juros** — ``juros_abonado`` sobe; o juros cobrado é o do atraso **menos** o perdoado
  (o juros dos dias seguintes continua correndo).
* **Nova data** — a data de cobrança da parcela muda e o juros passa a contar a partir dela; a
  data antiga fica em ``data_original``.

Um acordo só vale para parcela em aberto e sem baixa, e pode ser **desfeito** enquanto ela não for paga.
"""

import datetime
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.pagamentos import atraso

from .models import Acordo, CobrancaCora, Vencimento

Aviso = tuple[str, str]  # (nível da mensagem, texto)


class AcordoInvalido(Exception):
    """Pedido de acordo que não pode ser aplicado (a mensagem já é para o usuário)."""


def juros_do_atraso(vencimento: Vencimento, hoje: datetime.date) -> Decimal:
    """Juros do atraso até hoje, antes de qualquer perdão."""
    contrato = vencimento.contrato
    dias = atraso.dias_de_atraso(vencimento.data_vencimento, hoje, contrato.estrutura)
    return atraso.juros_acumulados(dias, contrato.juros_diario)


def juros_a_cobrar(vencimento: Vencimento, hoje: datetime.date) -> Decimal:
    """Juros que ainda se cobram hoje nesta parcela (atraso menos o que foi perdoado)."""
    return max(Decimal("0.00"), juros_do_atraso(vencimento, hoje) - vencimento.juros_abonado)


def motivo_para_nao_negociar(vencimento: Vencimento) -> str:
    """Texto explicando por que a parcela não aceita acordo; vazio quando aceita."""
    if vencimento.contrato.quitado:
        return "O contrato já está quitado."
    if vencimento.status == Vencimento.Status.PAGO:
        return "Esta parcela já está paga."
    if vencimento.pagamentos.exists():
        return "Esta parcela já recebeu pagamento (parcial): registre o restante em vez de negociar."
    return ""


def _renovar_pix(vencimento: Vencimento, motivo: str = "Acordo na parcela", autor=None) -> list[Aviso]:
    """Cancela o Pix aberto da parcela para a próxima rotina gerar outro com o valor combinado."""
    from . import cora_api
    from .pix_cora import CancelamentoRecusado, cancelar_cobranca, retomar_cobranca

    pix = CobrancaCora.objects.filter(vencimento=vencimento).first()
    if pix is not None and settings.PIX_MODO == "estatico" and pix.status not in (CobrancaCora.Status.PAGO, CobrancaCora.Status.CANCELADO):
        # Pix estático não tem fatura na Cora: remonta o código na hora com o valor novo, senão o cliente
        # pagaria o valor antigo até a próxima rotina (8h30).
        from .pix_cora import obter_ou_criar_cobranca
        obter_ou_criar_cobranca(vencimento)
        return []
    if pix is None or not pix.cora_id or pix.status in (CobrancaCora.Status.PAGO, CobrancaCora.Status.CANCELADO):
        return []  # sem QR vivo: a próxima rotina já usa os valores novos
    numero = vencimento.numero
    try:
        cancelar_cobranca(pix, motivo=motivo, autor=autor)
        retomar_cobranca(pix)
    except CancelamentoRecusado:
        return [("warning", f"O cliente já pagou o Pix da parcela {numero}: confira no painel Pix antes de seguir com o acordo.")]
    except cora_api.CoraErro:
        return [(
            "warning",
            f"Acordo registrado, mas não consegui cancelar o Pix antigo da parcela {numero} na Cora. "
            "Cancele-o no painel Pix, senão o cliente ainda pode pagar o valor antigo.",
        )]
    return [("info", f"O Pix antigo da parcela {numero} foi cancelado; a próxima rotina gera outro com o valor combinado.")]


@transaction.atomic
def aplicar_acordo(
    vencimento: Vencimento, *, tipo: str, autor=None, hoje: datetime.date | None = None,
    nova_data: datetime.date | None = None, juros_perdoar: Decimal | None = None, nota: str = "",
) -> tuple[Acordo, list[Aviso]]:
    """Aplica o acordo na parcela. Devolve o registro e avisos sobre o Pix. Levanta ``AcordoInvalido``."""
    hoje = hoje or timezone.localdate()
    vencimento = Vencimento.objects.select_for_update().select_related("contrato").get(pk=vencimento.pk)
    if motivo := motivo_para_nao_negociar(vencimento):
        raise AcordoInvalido(motivo)

    abono_anterior = vencimento.juros_abonado
    data_anterior = vencimento.data_vencimento
    perdoados = Decimal("0.00")
    if tipo == Acordo.Tipo.PERDAO_JUROS:
        cobrado = juros_a_cobrar(vencimento, hoje)
        if cobrado <= 0:
            raise AcordoInvalido("Esta parcela não tem juros para perdoar.")
        perdoados = (juros_perdoar if juros_perdoar is not None else cobrado).quantize(Decimal("0.01"))
        if perdoados <= 0 or perdoados > cobrado:
            raise AcordoInvalido(f"Informe um valor de juros entre R$ 0,01 e R$ {cobrado:.2f}.".replace(".", ","))
        vencimento.juros_abonado = abono_anterior + perdoados
        campos = ["juros_abonado", "atualizado_em"]
    elif tipo == Acordo.Tipo.NOVA_DATA:
        if nova_data is None:
            raise AcordoInvalido("Informe a nova data de cobrança.")
        if nova_data <= vencimento.data_vencimento:
            raise AcordoInvalido("A nova data precisa ser depois da data de cobrança atual da parcela.")
        if nova_data < hoje:
            raise AcordoInvalido("A nova data não pode estar no passado.")
        seguinte = vencimento.contrato.vencimentos.filter(numero__gt=vencimento.numero).order_by("numero").first()
        if seguinte and nova_data > seguinte.data_vencimento:
            raise AcordoInvalido(
                f"A nova data não pode passar do data de cobrança da parcela seguinte ({seguinte.data_vencimento:%d/%m/%Y})."
            )
        vencimento.data_original = vencimento.data_original or data_anterior
        vencimento.data_vencimento = nova_data
        vencimento.juros_abonado = Decimal("0.00")  # o juros recomeça a contar da nova data
        campos = ["data_original", "data_vencimento", "juros_abonado", "atualizado_em"]
    else:
        raise AcordoInvalido("Escolha o tipo de acordo.")

    vencimento.save(update_fields=campos)
    acordo = Acordo.objects.create(
        contrato=vencimento.contrato, vencimento=vencimento, tipo=tipo, juros_perdoados=perdoados,
        data_anterior=data_anterior if tipo == Acordo.Tipo.NOVA_DATA else None,
        nova_data=nova_data if tipo == Acordo.Tipo.NOVA_DATA else None,
        abono_anterior=abono_anterior, nota=nota.strip()[:200], autor=autor,
    )
    return acordo, _renovar_pix(vencimento, "Acordo na parcela", autor)


@transaction.atomic
def desfazer_acordo(acordo: Acordo, *, autor=None) -> list[Aviso]:
    """Volta a parcela ao que era antes do acordo. Levanta ``AcordoInvalido`` se não for mais possível."""
    acordo = Acordo.objects.select_for_update().get(pk=acordo.pk)
    if not acordo.ativo:
        raise AcordoInvalido("Este acordo já foi desfeito.")
    vencimento = Vencimento.objects.select_for_update().select_related("contrato").get(pk=acordo.vencimento_id)
    if motivo := motivo_para_nao_negociar(vencimento):
        raise AcordoInvalido(f"Não dá para desfazer: {motivo[0].lower()}{motivo[1:]}")
    posterior = vencimento.acordos.filter(desfeito_em__isnull=True, criado_em__gt=acordo.criado_em).exists()
    if posterior:
        raise AcordoInvalido("Desfaça primeiro o acordo mais recente desta parcela.")

    if acordo.tipo == Acordo.Tipo.NOVA_DATA:
        if vencimento.data_vencimento != acordo.nova_data:
            raise AcordoInvalido("A data da parcela mudou depois deste acordo; não dá para restaurar.")
        vencimento.data_vencimento = acordo.data_anterior
        anteriores = vencimento.acordos.filter(
            tipo=Acordo.Tipo.NOVA_DATA, desfeito_em__isnull=True, criado_em__lt=acordo.criado_em
        ).order_by("criado_em")
        vencimento.data_original = anteriores.first().data_anterior if anteriores.exists() else None
    vencimento.juros_abonado = acordo.abono_anterior
    vencimento.save(update_fields=["data_vencimento", "data_original", "juros_abonado", "atualizado_em"])

    acordo.desfeito_em = timezone.now()
    acordo.desfeito_por = autor
    acordo.save(update_fields=["desfeito_em", "desfeito_por"])
    return _renovar_pix(vencimento, "Acordo desfeito", autor)


def pode_desfazer(acordo: Acordo) -> bool:
    """O acordo ainda pode ser desfeito (ativo, parcela sem pagamento e sem acordo mais novo)."""
    if not acordo.ativo or motivo_para_nao_negociar(acordo.vencimento):
        return False
    return not acordo.vencimento.acordos.filter(desfeito_em__isnull=True, criado_em__gt=acordo.criado_em).exists()
