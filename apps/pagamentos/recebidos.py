"""Pix recebidos direto na Cora (transferência comum) que ainda não viraram baixa no sistema.

O webhook da Cora só avisa dos QR codes gerados pelo sistema. Quem paga pela chave Pix cai no extrato,
sem parcela ligada. Aqui o extrato é lido (só leitura), cada entrada vira um `RecebimentoCora` e o sistema
sugere de quem é (pelo CPF e, na falta dele, pelo nome) para a equipe registrar o pagamento com um clique.
"""

import datetime
import re
import unicodedata

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import cora_api
from .models import CobrancaCora, RecebimentoCora

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
        RecebimentoCora.objects.create(
            entrada_id=entrada["id"], valor=entrada["valor"], recebido_em=entrada["recebido_em"],
            tipo=entrada["tipo"], nome=entrada["nome"], documento=entrada["documento"],
            situacao=RecebimentoCora.Situacao.VINCULADO if de_fatura else RecebimentoCora.Situacao.NOVO,
            tratado_em=timezone.now() if de_fatura else None,
        )
    cache.set(_CHAVE_SINCRONIA, True, _TTL_SINCRONIA)
    return ""


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
