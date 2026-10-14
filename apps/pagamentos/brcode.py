"""Código Pix "copia e cola" estático (BR Code), montado aqui, sem chamar nenhum banco.

Formato EMV do Banco Central: uma sequência de campos ``ID + tamanho (2 dígitos) + valor`` terminada pelo CRC16.
O código leva a **chave Pix** do recebedor, o **valor** e uma **referência** (txid) que identifica a parcela.
Como é estático, não expira e não pode ser cancelado: cada dia sai um código novo com o valor atualizado.
"""

import re
import unicodedata
from decimal import Decimal


def _campo(identificador: str, valor: str) -> str:
    return f"{identificador}{len(valor):02d}{valor}"


def _crc16(texto: str) -> str:
    """CRC16/CCITT-FALSE (polinômio 0x1021, início 0xFFFF), em 4 dígitos hexadecimais maiúsculos."""
    crc = 0xFFFF
    for byte in texto.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _texto(valor: str, tamanho: int) -> str:
    """Sem acento, só letras/números/espaço, em maiúsculas e cortado no tamanho do campo."""
    sem_acento = unicodedata.normalize("NFKD", valor or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", sem_acento).upper().strip()[:tamanho]


def copia_e_cola(*, chave: str, valor: Decimal, nome: str, cidade: str, referencia: str = "***") -> str:
    """Monta o código Pix estático com valor. ``referencia`` (txid) usa só letras e números, até 25."""
    if not chave:
        raise ValueError("A chave Pix não está configurada.")
    valor = Decimal(valor).quantize(Decimal("0.01"))
    if valor <= 0:
        raise ValueError("O valor do Pix precisa ser maior que zero.")
    txid = re.sub(r"[^A-Za-z0-9]", "", referencia)[:25] or "***"
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave.strip())
    corpo = (
        _campo("00", "01")
        + _campo("01", "11")  # 11 = estático (reutilizável)
        + _campo("26", conta)
        + _campo("52", "0000")
        + _campo("53", "986")
        + _campo("54", f"{valor:.2f}")
        + _campo("58", "BR")
        + _campo("59", _texto(nome, 25) or "RECEBEDOR")
        + _campo("60", _texto(cidade, 15) or "BRASIL")
        + _campo("62", _campo("05", txid))
        + "6304"
    )
    return corpo + _crc16(corpo)
