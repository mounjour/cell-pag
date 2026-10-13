"""Bloqueio de aparelhos por atraso: o que bloquear, o que já está bloqueado e o que liberar.

O sistema só **sinaliza** (7 dias de atraso, ver ``apps.pagamentos.atraso``); bloquear o
celular é ação manual. Aqui fica o controle do que a equipe já fez:

* **Para bloquear** — atraso de 7+ dias e sem bloqueio registrado.
* **Bloqueados** — bloqueio ativo e o cliente ainda deve.
* **Para desbloquear** — bloqueio ativo, mas o cliente regularizou (sem atraso) ou quitou.
"""

import datetime

from django.utils import timezone

from .models import BloqueioAparelho


def bloqueios_ativos():
    return BloqueioAparelho.objects.filter(desbloqueado_em__isnull=True)


def ids_dos_contratos_bloqueados() -> set[int]:
    return set(bloqueios_ativos().values_list("contrato_id", flat=True))


def _dias_de_atraso(contrato, hoje: datetime.date) -> int:
    situacao = contrato.situacao_atraso(hoje=hoje)
    return situacao.dias_atraso if situacao else 0


def regularizado(contrato, hoje: datetime.date) -> bool:
    """O cliente voltou a ficar sem atraso (ou quitou): o aparelho pode ser liberado."""
    return contrato.quitado or _dias_de_atraso(contrato, hoje) == 0


def contar_a_desbloquear(hoje: datetime.date | None = None) -> int:
    hoje = hoje or timezone.localdate()
    ativos = bloqueios_ativos().select_related("contrato")
    return sum(1 for bloqueio in ativos if regularizado(bloqueio.contrato, hoje))


def montar_painel(hoje: datetime.date | None = None) -> dict:
    """Tudo o que a tela de bloqueios mostra, num só lugar."""
    from apps.pagamentos.agenda import montar_agenda_do_dia, resumo_cobranca

    hoje = hoje or timezone.localdate()
    agenda = montar_agenda_do_dia(hoje)
    a_bloquear = [
        linha for linha in agenda["linhas"] if linha["situacao"].alertar_bloqueio and not linha["bloqueado"]
    ]

    bloqueados, para_desbloquear = [], []
    ativos = bloqueios_ativos().select_related("contrato__cliente", "contrato__aparelho", "bloqueado_por")
    for bloqueio in ativos.order_by("bloqueado_em"):
        contrato = bloqueio.contrato
        dias = _dias_de_atraso(contrato, hoje)
        if regularizado(contrato, hoje):
            para_desbloquear.append({"bloqueio": bloqueio, "quitado": contrato.quitado})
        else:
            bloqueados.append(
                {"bloqueio": bloqueio, "dias_atraso": dias, "a_cobrar": resumo_cobranca(contrato, hoje)["total"]}
            )
    bloqueados.sort(key=lambda item: -item["dias_atraso"])

    historico = (
        BloqueioAparelho.objects.filter(desbloqueado_em__isnull=False)
        .select_related("contrato__cliente", "bloqueado_por", "desbloqueado_por")
        .order_by("-desbloqueado_em")[:15]
    )
    return {
        "hoje": hoje,
        "a_bloquear": a_bloquear,
        "bloqueados": bloqueados,
        "para_desbloquear": para_desbloquear,
        "historico": historico,
    }
