"""Entrega autenticada de anexos (comprovantes, documentos de contrato).

Os arquivos NÃO são servidos por URL pública de mídia: só saem por uma view
com login, sempre como download (`attachment`) e com cabeçalhos que impedem o
navegador de renderizar/adivinhar o conteúdo — assim um upload malicioso (HTML,
SVG) não vira XSS mesmo se o dia de amanhã ligar um disco persistente.
"""

import os

from django.http import FileResponse, Http404


def servir_anexo(filefield) -> FileResponse:
    if not filefield:
        raise Http404("Arquivo não encontrado.")
    try:
        conteudo = filefield.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Arquivo não encontrado.") from exc

    resposta = FileResponse(
        conteudo,
        as_attachment=True,
        filename=os.path.basename(filefield.name),
    )
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Content-Security-Policy"] = "default-src 'none'; sandbox"
    resposta["Cache-Control"] = "private, no-store"
    return resposta
