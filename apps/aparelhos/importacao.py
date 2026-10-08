"""Importação de aparelhos (estoque) por CSV: lê, valida e classifica cada linha.

Só entra aparelho com **modelo e IMEI de 15 dígitos**. IMEI inválido, repetido no
arquivo ou já cadastrado ficam de fora — a prévia mostra cada um com o motivo.
Custo, fornecedor, data da compra e observações são opcionais. Nada é gravado aqui.

Planilhas costumam mostrar o IMEI em notação científica ("3,57E+14") e perder
dígitos; esse caso é rejeitado como inválido em vez de adivinhar.
"""

import csv
import datetime
import io
import re
import unicodedata
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.contratos.forms import moeda_para_decimal

from .catalogo import MODELOS_IPHONE
from .models import Aparelho

MAX_LINHAS = 2000

# Cabeçalhos aceitos (sem acento, minúsculos, só letras/números) → campo.
_COLUNAS = {
    "modelo": "modelo", "aparelho": "modelo", "celular": "modelo",
    "imei": "imei", "emei": "imei",
    "custo": "custo", "custodecompra": "custo", "valor": "custo",
    "fornecedor": "fornecedor",
    "datadacompra": "data_compra", "datacompra": "data_compra", "compra": "data_compra",
    "observacoes": "observacoes", "observacao": "observacoes", "obs": "observacoes",
}

NOVO, JA_CADASTRADO, REPETIDO, REJEITADO = "novo", "ja_cadastrado", "repetido", "rejeitado"

_MODELOS_CANONICOS = {re.sub(r"\s+", " ", m).lower(): m for m in MODELOS_IPHONE}


def _chave_cabecalho(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", valor or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def _decodificar(conteudo: bytes) -> str:
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1")


def _modelo(bruto: str) -> str:
    """Normaliza espaços e usa a grafia do catálogo quando o modelo é conhecido."""
    texto = re.sub(r"\s+", " ", bruto or "").strip()
    return _MODELOS_CANONICOS.get(texto.lower(), texto)


def _imei(bruto: str):
    """Devolve ``(imei_15_digitos, erro)``."""
    texto = (bruto or "").strip()
    if not texto:
        return "", "IMEI ausente."
    if re.search(r"\d[.,]?\d*e\+?\d+", texto, flags=re.IGNORECASE):
        return "", "IMEI em notação científica (a planilha perdeu dígitos)."
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) != 15:
        return "", "IMEI deve ter 15 dígitos."
    return digitos, ""


def _custo(bruto: str):
    texto = re.sub(r"(?i)r\$", "", bruto or "").strip()
    if not texto:
        return None, ""
    try:
        valor = moeda_para_decimal(texto)
    except ValidationError:
        return None, "Custo inválido."
    if valor is None or valor < 0 or valor >= 10**8:
        return None, "Custo inválido."
    return valor.quantize(Decimal("0.01")), ""


def _data(bruto: str):
    texto = (bruto or "").strip()
    if not texto:
        return None, ""
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(texto, formato).date(), ""
        except ValueError:
            continue
    return None, "Data da compra inválida (use DD/MM/AAAA)."


def analisar(conteudo: bytes):
    """Classifica as linhas do CSV. Devolve ``(linhas, erro_geral)``; não grava nada."""
    texto = _decodificar(conteudo)
    if not texto.strip():
        return [], "O arquivo está vazio."
    try:
        dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t")
    except csv.Error:
        dialeto = csv.excel
    linhas_csv = list(csv.reader(io.StringIO(texto), dialect=dialeto))
    campos = [_COLUNAS.get(_chave_cabecalho(c), "") for c in linhas_csv[0]]
    faltam = {"modelo", "imei"} - set(campos)
    if faltam:
        return [], "Colunas obrigatórias ausentes: " + ", ".join(sorted(faltam)) + "."
    if len(linhas_csv) - 1 > MAX_LINHAS:
        return [], f"O arquivo tem linhas demais (máximo {MAX_LINHAS})."

    existentes = set(Aparelho.objects.exclude(imei__isnull=True).values_list("imei", flat=True))
    vistos = set()
    resultado = []
    for numero, valores in enumerate(linhas_csv[1:], start=2):
        if not any((v or "").strip() for v in valores):
            continue
        bruto = {campos[i]: (valores[i] or "").strip() for i in range(min(len(campos), len(valores))) if campos[i]}
        modelo = _modelo(bruto.get("modelo", ""))
        imei, erro_imei = _imei(bruto.get("imei", ""))
        custo, erro_custo = _custo(bruto.get("custo", ""))
        data_compra, erro_data = _data(bruto.get("data_compra", ""))
        fornecedor = re.sub(r"\s+", " ", bruto.get("fornecedor", ""))
        linha = {
            "linha": numero, "modelo": modelo, "imei": imei or re.sub(r"\D", "", bruto.get("imei", "")),
            "custo": str(custo) if custo is not None else "", "fornecedor": fornecedor,
            "data_compra": data_compra.isoformat() if data_compra else "",
            "observacoes": bruto.get("observacoes", ""),
        }
        motivos = [m for m in ("Modelo ausente." if not modelo else "", erro_imei, erro_custo, erro_data) if m]
        if len(modelo) > 120:
            motivos.append("Modelo com mais de 120 caracteres.")
        if len(fornecedor) > 120:
            motivos.append("Fornecedor com mais de 120 caracteres.")
        if motivos:
            linha.update(situacao=REJEITADO, motivo=" ".join(motivos))
        elif imei in existentes:
            linha.update(situacao=JA_CADASTRADO, motivo="IMEI já cadastrado no estoque.")
        elif imei in vistos:
            linha.update(situacao=REPETIDO, motivo="IMEI repetido no arquivo.")
        else:
            vistos.add(imei)
            linha.update(situacao=NOVO, motivo="")
        resultado.append(linha)
    if not resultado:
        return [], "Nenhuma linha de aparelho encontrada no arquivo."
    return resultado, ""


def resumir(linhas):
    contagem = {NOVO: 0, JA_CADASTRADO: 0, REPETIDO: 0, REJEITADO: 0}
    for linha in linhas:
        contagem[linha["situacao"]] += 1
    return {
        "total": len(linhas), "novos": contagem[NOVO], "de_fora": len(linhas) - contagem[NOVO],
        "ja_cadastrados": contagem[JA_CADASTRADO], "repetidos": contagem[REPETIDO],
        "rejeitados": contagem[REJEITADO],
    }


def gravar(linhas):
    """Cria os aparelhos das linhas ``novo`` (revalida cada uma). Devolve quantos entraram."""
    criados = 0
    for linha in linhas:
        if linha.get("situacao") != NOVO or Aparelho.objects.filter(imei=linha["imei"]).exists():
            continue
        aparelho = Aparelho(
            modelo=linha["modelo"], imei=linha["imei"], fornecedor=linha.get("fornecedor", ""),
            custo=linha["custo"] or None,
            data_compra=datetime.date.fromisoformat(linha["data_compra"]) if linha.get("data_compra") else None,
            observacoes=linha.get("observacoes", ""),
        )
        try:
            aparelho.full_clean()
        except ValidationError:
            continue
        aparelho.save()
        criados += 1
    return criados
