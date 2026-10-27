"""Conector do Claude Desktop para o Sistema de Acompanhamento de Pagamentos de Celulares.

Este programa roda no computador de quem usa o Claude Desktop. Ele não guarda dados: a cada pedido do Claude
ele conversa com o sistema pela internet, usando a chave de acesso da pessoa.

Configuração (variáveis de ambiente, definidas no arquivo de configuração do Claude Desktop):
    CELULARES_URL    endereço do sistema, ex.: https://celulares-pag.duckdns.org
    CELULARES_CHAVE  a chave criada na tela "Claude Desktop" do sistema (começa com cp_)

Instalação (uma vez):  pip install "mcp<2"
"""

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server

URL = os.environ.get("CELULARES_URL", "").rstrip("/")
CHAVE = os.environ.get("CELULARES_CHAVE", "")

servidor = Server("celulares")
_gravam: set[str] = set()
INTERVALO_DE_VIGILIA = 60  # segundos entre conferir se o sistema ganhou ferramentas novas
_sessao = None  # a conversa com o Claude Desktop, para avisar quando a lista de ferramentas mudar
_assinatura = None


def _chamar(caminho: str, corpo: dict | None = None) -> tuple[int, dict]:
    if not URL or not CHAVE:
        return 0, {"erro": "Faltam CELULARES_URL e CELULARES_CHAVE na configuração do conector."}
    requisicao = urllib.request.Request(
        URL + caminho,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={
            "Authorization": f"Bearer {CHAVE}", "Content-Type": "application/json", "User-Agent": "celulares-mcp",
            **({"X-Teste": "1"} if os.environ.get("CELULARES_TESTE") == "1" else {}),  # teste do instalador: não conta como uso
        },
        method="POST" if corpo is not None else "GET",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=60) as resposta:
            return resposta.status, json.load(resposta)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, {"erro": f"O sistema respondeu com erro {exc.code}."}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"erro": f"Não consegui falar com o sistema: {exc}"}


def _ferramentas_do_sistema() -> list[dict]:
    status, dados = _chamar("/assistente/api/ferramentas/")
    if status != 200:
        raise RuntimeError(dados.get("erro", "Não consegui carregar as ferramentas do sistema."))
    return dados["ferramentas"]


def _assinar(itens: list[dict]) -> str:
    return json.dumps(itens, sort_keys=True, ensure_ascii=False)


@servidor.list_tools()
async def listar() -> list[types.Tool]:
    global _sessao, _assinatura
    _sessao = servidor.request_context.session
    itens = await asyncio.to_thread(_ferramentas_do_sistema)
    _assinatura = _assinar(itens)
    _gravam.clear()
    tools = []
    for f in itens:
        if f["grava"]:
            _gravam.add(f["name"])
        tools.append(types.Tool(
            name=f["name"], description=f["description"], inputSchema=f["input_schema"],
            annotations=types.ToolAnnotations(
                title=f["name"].replace("_", " "), readOnlyHint=not f["grava"], destructiveHint=False,
                idempotentHint=False, openWorldHint=False,
            ),
        ))
    return tools


@servidor.call_tool()
async def chamar(nome: str, argumentos: dict) -> list[types.TextContent]:
    status, dados = await asyncio.to_thread(_chamar, "/assistente/api/executar/", {"ferramenta": nome, "parametros": argumentos or {}})
    if status == 200 and dados.get("ok"):
        return [types.TextContent(type="text", text=dados["resultado"])]
    # Erro volta como resultado de erro: o Claude lê a mensagem e explica à pessoa.
    raise RuntimeError(dados.get("erro", f"Erro {status} ao falar com o sistema."))


async def _vigiar_ferramentas() -> None:
    """Se o sistema ganhar (ou mudar) ferramentas, avisa o Claude Desktop: a conversa aberta passa a vê-las."""
    global _assinatura
    while True:
        await asyncio.sleep(INTERVALO_DE_VIGILIA)
        if _sessao is None:
            continue
        try:
            nova = _assinar(await asyncio.to_thread(_ferramentas_do_sistema))
        except Exception:
            continue  # sistema fora do ar agora: tenta de novo no próximo ciclo
        if nova != _assinatura:
            _assinatura = nova
            try:
                await _sessao.send_tool_list_changed()
            except Exception:
                pass


async def principal() -> None:
    opcoes = servidor.create_initialization_options(notification_options=NotificationOptions(tools_changed=True))
    vigia = asyncio.create_task(_vigiar_ferramentas())
    try:
        async with stdio_server() as (leitura, escrita):
            await servidor.run(leitura, escrita, opcoes)
    finally:
        vigia.cancel()


if __name__ == "__main__":
    if "--testar" in sys.argv:
        for f in _ferramentas_do_sistema():
            print(("grava  " if f["grava"] else "le     ") + f["name"])
    else:
        asyncio.run(principal())
