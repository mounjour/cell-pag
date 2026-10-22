"""Instalador do conector do Claude Desktop (Windows).

Rodado pelo arquivo "Instalar-Claude-Desktop.cmd" baixado do sistema. Faz tudo sozinho:
  1. instala a peça "mcp" do Python, se ainda não estiver instalada;
  2. baixa o conector do sistema (usando a chave da pessoa) e guarda numa pasta fixa;
  3. ajusta a configuração do Claude Desktop, sem apagar o que já existe (e guarda uma cópia do arquivo antigo).

Uso:  python instalar_claude_desktop.py ENDERECO_DO_SISTEMA CHAVE
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

NOME_NO_CLAUDE = "celulares"


def mesclar(config: dict, python: str, script: str, url: str, chave: str) -> dict:
    """Devolve a configuração com o conector adicionado, mantendo tudo o que já havia."""
    novo = dict(config or {})
    servidores = dict(novo.get("mcpServers") or {})
    servidores[NOME_NO_CLAUDE] = {
        "command": python,
        "args": [script],
        "env": {"CELULARES_URL": url, "CELULARES_CHAVE": chave},
    }
    novo["mcpServers"] = servidores
    return novo


def caminhos_de_configuracao() -> list[Path]:
    """Onde o Claude Desktop guarda a configuração (instalação comum e instalação pela loja da Microsoft)."""
    roaming = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidatos = [roaming / "Claude" / "claude_desktop_config.json"]
    pacotes = local / "Packages"
    if pacotes.is_dir():
        candidatos += sorted(pacotes.glob("Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"))
        candidatos += [p.parent / "claude_desktop_config.json" for p in pacotes.glob("Claude_*/LocalCache/Roaming/Claude")]
    vistos, unicos = set(), []
    for c in candidatos:
        if c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return unicos


def baixar(url: str, chave: str, destino: Path) -> None:
    requisicao = urllib.request.Request(url, headers={"Authorization": f"Bearer {chave}", "User-Agent": "celulares-instalador"})
    with urllib.request.urlopen(requisicao, timeout=60) as resposta:
        destino.write_bytes(resposta.read())


def garantir_mcp() -> None:
    try:
        import mcp  # noqa: F401
        return
    except ImportError:
        pass
    print("Instalando a peça que o conector usa (pode levar um minuto)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "mcp<2"])


def principal(url: str, chave: str) -> int:
    url = url.rstrip("/")
    garantir_mcp()

    pasta = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CelularesMCP"
    pasta.mkdir(parents=True, exist_ok=True)
    script = pasta / "celulares_mcp.py"
    print("Baixando o conector do sistema...")
    baixar(f"{url}/assistente/api/conector.py", chave, script)

    escritos = []
    alvos = [c for c in caminhos_de_configuracao() if c.parent.is_dir()] or caminhos_de_configuracao()[:1]
    for caminho in alvos:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        atual = {}
        if caminho.exists():
            try:
                # utf-8-sig: o Bloco de Notas e outros programas do Windows às vezes gravam uma marca no início do arquivo.
                atual = json.loads(caminho.read_text(encoding="utf-8-sig") or "{}")
            except ValueError:
                print(f"Atenção: o arquivo {caminho} não é um JSON válido; não mexi nele.")
                continue
            shutil.copy2(caminho, caminho.with_suffix(".json.antes-do-celulares"))
        caminho.write_text(json.dumps(mesclar(atual, sys.executable, str(script), url, chave), indent=2, ensure_ascii=False), encoding="utf-8")
        escritos.append(caminho)

    if not escritos:
        print("Não consegui ajustar a configuração do Claude Desktop. Avise quem cuida do sistema.")
        return 1
    print()
    print("Pronto! Falta só uma coisa: FECHE O CLAUDE DESKTOP POR COMPLETO e abra de novo.")
    print("(Se ele ficar na bandeja perto do relógio, clique com o botão direito e escolha Sair.)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python instalar_claude_desktop.py ENDERECO_DO_SISTEMA CHAVE")
        sys.exit(2)
    try:
        sys.exit(principal(sys.argv[1], sys.argv[2]))
    except Exception as erro:  # noqa: BLE001 — mostra o motivo em linguagem simples
        print(f"Não deu certo: {erro}")
        sys.exit(1)
