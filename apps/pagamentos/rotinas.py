"""Saúde das rotinas agendadas: registra cada execução e diz se alguma parou ou falhou.

As rotinas (cobranças, leitura do extrato da Cora…) rodam sozinhas, de madrugada ou a cada poucos minutos, no
agendador do servidor. Se uma para de rodar ou começa a falhar, ninguém percebe até um cliente deixar de ser
cobrado ou um Pix ficar sem baixa. Aqui cada comando agendado deixa uma marca ao começar e outra ao terminar,
e a tela "Saúde das rotinas" mostra a última vez de cada um.
"""

import datetime
import logging
from contextlib import contextmanager

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from .models import ExecucaoRotina

logger = logging.getLogger(__name__)

# nome do comando -> (rótulo, o que faz, de quanto em quanto tempo deve rodar no máximo, em horas)
ROTINAS = {
    "rotina_diaria": ("Rotina diária", "Gera as parcelas, avisa quem cobrar hoje e dispara as cobranças da manhã.", 26),
    "enviar_cobrancas_clientes": ("Cobranças aos clientes", "Envia as mensagens e atualiza o código Pix de cada parcela do dia.", 26),
    "conferir_recebidos": ("Leitura do extrato da Cora", "Lê os Pix que entraram na Cora e dá a baixa automática.", 2),
    "gerar_vencimentos": ("Geração de parcelas", "Cria as parcelas dos próximos 60 dias e atualiza o status dos contratos.", 26),
    "enviar_lembrete_diario": ("Lembrete de cobrança do dia", "Manda o resumo de quem cobrar hoje.", 26),
}

_CHAVE_PROBLEMAS = "rotinas_com_problema_n"
_PRAZO_TRAVADA = datetime.timedelta(minutes=45)


@contextmanager
def registrar(nome: str):
    """Marca o começo da rotina e, ao sair, se terminou bem ou com erro (o erro continua subindo).

    O registro nunca pode derrubar a rotina: se o banco falhar ao gravar a marca, a rotina segue sem ela.
    """
    try:
        execucao = ExecucaoRotina.objects.create(nome=nome)
        ExecucaoRotina.objects.filter(nome=nome, iniciada_em__lt=timezone.now() - datetime.timedelta(days=30)).delete()
        cache.delete(_CHAVE_PROBLEMAS)
    except Exception:
        logger.warning("Não consegui registrar o início da rotina %s", nome, exc_info=True)
        execucao = None
    try:
        yield execucao
    except BaseException as exc:
        if execucao is not None:
            execucao.sucesso, execucao.erro = False, str(exc)[:500] or exc.__class__.__name__
        raise
    else:
        if execucao is not None:
            execucao.sucesso = True
    finally:
        if execucao is not None:
            try:
                execucao.terminada_em = timezone.now()
                execucao.save(update_fields=["sucesso", "erro", "terminada_em"])
                cache.delete(_CHAVE_PROBLEMAS)
            except Exception:
                logger.warning("Não consegui registrar o fim da rotina %s", nome, exc_info=True)


class ComandoRegistrado(BaseCommand):
    """Comando de gerenciamento que deixa o registro da execução (use no lugar de ``BaseCommand``)."""

    nome_rotina = ""

    def execute(self, *args, **options):
        with registrar(self.nome_rotina):
            return super().execute(*args, **options)


def situacao_das_rotinas(agora=None) -> list[dict]:
    """Uma linha por rotina: última execução, última que deu certo e o estado (ok, falhou, atrasada, travada)."""
    agora = agora or timezone.now()
    linhas = []
    for nome, (rotulo, descricao, max_horas) in ROTINAS.items():
        execucoes = ExecucaoRotina.objects.filter(nome=nome)
        ultima = execucoes.first()
        ultima_ok = execucoes.filter(sucesso=True).first()
        if ultima is None:
            estado = "sem_registro"
        elif ultima.sucesso is False:
            estado = "falhou"
        elif ultima.sucesso is None and agora - ultima.iniciada_em > _PRAZO_TRAVADA:
            estado = "travada"
        elif ultima_ok is None or agora - ultima_ok.terminada_em > datetime.timedelta(hours=max_horas):
            estado = "atrasada"
        else:
            estado = "ok"
        linhas.append({
            "nome": nome, "rotulo": rotulo, "descricao": descricao, "max_horas": max_horas, "estado": estado,
            "ultima": ultima, "ultima_ok": ultima_ok, "recentes": list(execucoes[:5]),
        })
    return linhas


def rotinas_com_problema() -> int:
    """Quantas rotinas pedem atenção (falharam, pararam ou travaram). Guardado por 1 minuto para o menu."""
    guardado = cache.get(_CHAVE_PROBLEMAS)
    if guardado is None:
        guardado = sum(linha["estado"] in {"falhou", "atrasada", "travada"} for linha in situacao_das_rotinas())
        cache.set(_CHAVE_PROBLEMAS, guardado, 60)
    return guardado


def versao_publicada() -> dict:
    """Compara o commit que está no ar com o último da ``main`` no GitHub (repositório público, só leitura).

    ``estado``: ``ok`` (iguais), ``atrasada`` (há commit novo na main que ainda não foi publicado) ou
    ``desconhecida`` (o servidor não informou o commit, ou o GitHub não respondeu).
    """
    import json
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    from django.conf import settings

    publicada = (settings.VERSAO_PUBLICADA or "").strip()
    resultado = {"publicada": publicada, "ultima": "", "estado": "desconhecida", "motivo": ""}
    if not publicada:
        resultado["motivo"] = "O servidor não informou qual commit está publicado."
        return resultado
    ultima = cache.get("versao_main_github")
    if ultima is None:
        try:
            requisicao = Request(
                f"https://api.github.com/repos/{settings.REPOSITORIO_GITHUB}/commits/main",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "cell-pag"},
            )
            with urlopen(requisicao, timeout=4) as resposta:  # noqa: S310 (URL fixa, https)
                ultima = json.load(resposta).get("sha", "")
            cache.set("versao_main_github", ultima, 300)
        except (URLError, TimeoutError, ValueError, OSError):
            resultado["motivo"] = "Não consegui consultar o GitHub agora."
            return resultado
    resultado["ultima"] = ultima
    resultado["estado"] = "ok" if ultima.startswith(publicada) or publicada.startswith(ultima) else "atrasada"
    return resultado
