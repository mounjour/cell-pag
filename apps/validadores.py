"""Validadores compartilhados de upload de arquivo.

Aplicados nos ``FileField`` (comprovante de pagamento, documento de contrato).
Rodam na validação do ModelForm — que é o único caminho de upload (formulário
web e admin).
"""

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

EXTENSOES_UPLOAD = ["pdf", "jpg", "jpeg", "png", "webp"]
TAMANHO_MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB

validar_extensao_upload = FileExtensionValidator(allowed_extensions=EXTENSOES_UPLOAD)


def validar_tamanho_upload(arquivo):
    tamanho = getattr(arquivo, "size", None)
    if tamanho and tamanho > TAMANHO_MAX_UPLOAD:
        raise ValidationError(
            "Arquivo muito grande (máx. %d MB)." % (TAMANHO_MAX_UPLOAD // (1024 * 1024))
        )
