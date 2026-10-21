"""Anexos do chat (imagens, PDF e texto): conferidos pelo conteúdo e convertidos nos blocos que o Claude entende."""

import base64

MAX_ARQUIVOS = 4
MAX_BYTES_POR_ARQUIVO = 4_500_000
MAX_BYTES_TOTAL = 10_000_000
MAX_CARACTERES_TEXTO = 60_000

_ASSINATURAS_DE_IMAGEM = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


class AnexoInvalido(Exception):
    """Arquivo recusado (a mensagem é para a pessoa)."""


def _tipo_pelo_conteudo(dados: bytes, nome: str) -> str:
    """Descobre o tipo olhando os primeiros bytes (a extensão e o tipo informado pelo navegador não valem)."""
    for assinatura, tipo in _ASSINATURAS_DE_IMAGEM:
        if dados.startswith(assinatura):
            return tipo
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    if dados.startswith(b"%PDF"):
        return "application/pdf"
    if nome.lower().endswith((".txt", ".csv")):
        try:
            dados.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    raise AnexoInvalido(f"“{nome}”: só aceito imagens (PNG, JPG, WEBP, GIF), PDF e arquivos .txt ou .csv.")


def preparar(arquivos) -> tuple[list[dict], list[str]]:
    """Valida os arquivos e devolve (blocos para o Claude, nomes mostrados na tela)."""
    arquivos = list(arquivos)
    if len(arquivos) > MAX_ARQUIVOS:
        raise AnexoInvalido(f"Envie no máximo {MAX_ARQUIVOS} arquivos por mensagem.")
    blocos: list[dict] = []
    nomes: list[str] = []
    total = 0
    for arquivo in arquivos:
        nome = (arquivo.name or "arquivo")[:80]
        if arquivo.size > MAX_BYTES_POR_ARQUIVO:
            raise AnexoInvalido(f"“{nome}” é grande demais (máximo {MAX_BYTES_POR_ARQUIVO // 1_000_000} MB por arquivo).")
        total += arquivo.size
        if total > MAX_BYTES_TOTAL:
            raise AnexoInvalido("Os arquivos juntos passam do limite de 10 MB.")
        dados = arquivo.read()
        tipo = _tipo_pelo_conteudo(dados, nome)
        blocos.append({"type": "text", "text": f"[Anexo: {nome}]"})
        if tipo == "text/plain":
            texto = dados.decode("utf-8")[:MAX_CARACTERES_TEXTO]
            blocos.append({"type": "text", "text": f"Conteúdo do arquivo {nome}:\n{texto}"})
        else:
            origem = {"type": "base64", "media_type": tipo, "data": base64.standard_b64encode(dados).decode("ascii")}
            blocos.append({"type": "document" if tipo == "application/pdf" else "image", "source": origem})
        nomes.append(nome)
    return blocos, nomes
