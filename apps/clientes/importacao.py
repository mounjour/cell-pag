"""Importação de clientes por CSV: lê, valida e classifica cada linha.

Só entra quem tem **nome, CPF válido e telefone válido**. CPF incompleto ou
inválido, telefone ausente/inválido, CPF repetido no arquivo e CPF já cadastrado
ficam de fora — a prévia mostra cada um com o motivo. Nada é gravado aqui.

Planilhas perdem o zero à esquerda do CPF ("06786825316" vira 6786825316).
Quando faltam dígitos, completar com zeros só é aceito se o resultado passar na
validação dos dígitos verificadores; senão a linha é rejeitada como incompleta.
"""

import csv
import io
import re
import unicodedata

from django.core.exceptions import ValidationError
from phonenumber_field.phonenumber import PhoneNumber

from .models import Cliente, so_digitos, valida_cpf

MAX_LINHAS = 2000

# Cabeçalhos aceitos (sem acento, minúsculos, só letras/números) → campo.
_COLUNAS = {
    "nome": "nome", "cliente": "nome", "nomecompleto": "nome",
    "cpf": "cpf",
    "telefone": "telefone", "contato": "telefone", "whatsapp": "telefone",
    "telefonewhatsapp": "telefone", "celular": "telefone",
    "endereco": "endereco",
}

NOVO, JA_CADASTRADO, REPETIDO, REJEITADO = "novo", "ja_cadastrado", "repetido", "rejeitado"


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


def _cpf(bruto: str):
    """Devolve ``(cpf_11_digitos, erro)``."""
    digitos = so_digitos(bruto)
    if not digitos:
        return "", "CPF ausente."
    if len(digitos) > 11:
        return "", "CPF com mais de 11 dígitos."
    candidato = digitos.zfill(11)
    try:
        valida_cpf(candidato)
    except ValidationError:
        return "", "CPF incompleto." if len(digitos) < 11 else "CPF inválido."
    return candidato, ""


def _telefone(bruto: str):
    """Devolve ``(telefone_e164, erro)``."""
    if not so_digitos(bruto):
        return "", "Telefone ausente."
    telefone = PhoneNumber.from_string(bruto, region="BR")
    if not telefone.is_valid():
        return "", "Telefone inválido."
    return telefone.as_e164, ""


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
    faltam = {"nome", "cpf", "telefone"} - set(campos)
    if faltam:
        return [], "Colunas obrigatórias ausentes: " + ", ".join(sorted(faltam)) + "."
    if len(linhas_csv) - 1 > MAX_LINHAS:
        return [], f"O arquivo tem linhas demais (máximo {MAX_LINHAS})."

    existentes = set(Cliente.objects.values_list("cpf", flat=True))
    vistos = set()
    resultado = []
    for numero, valores in enumerate(linhas_csv[1:], start=2):
        if not any((v or "").strip() for v in valores):
            continue
        bruto = {campos[i]: (valores[i] or "").strip() for i in range(min(len(campos), len(valores))) if campos[i]}
        nome = re.sub(r"\s+", " ", bruto.get("nome", ""))
        cpf, erro_cpf = _cpf(bruto.get("cpf", ""))
        telefone, erro_telefone = _telefone(bruto.get("telefone", ""))
        linha = {
            "linha": numero, "nome": nome, "cpf": cpf or so_digitos(bruto.get("cpf", "")),
            "telefone": telefone or bruto.get("telefone", ""), "endereco": bruto.get("endereco", ""),
        }
        motivos = [m for m in ("Nome ausente." if not nome else "", erro_cpf, erro_telefone) if m]
        if len(nome) > 150:
            motivos.append("Nome com mais de 150 caracteres.")
        if motivos:
            linha.update(situacao=REJEITADO, motivo=" ".join(motivos))
        elif cpf in existentes:
            linha.update(situacao=JA_CADASTRADO, motivo="CPF já cadastrado.")
        elif cpf in vistos:
            linha.update(situacao=REPETIDO, motivo="CPF repetido no arquivo.")
        else:
            vistos.add(cpf)
            linha.update(situacao=NOVO, motivo="")
        resultado.append(linha)
    if not resultado:
        return [], "Nenhuma linha de cliente encontrada no arquivo."
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
    """Cria os clientes das linhas ``novo`` (revalida cada uma). Devolve quantos entraram."""
    criados = 0
    for linha in linhas:
        if linha.get("situacao") != NOVO or Cliente.objects.filter(cpf=linha["cpf"]).exists():
            continue
        cliente = Cliente(
            nome=linha["nome"], cpf=linha["cpf"], telefone_whatsapp=linha["telefone"],
            endereco=linha.get("endereco", ""),
        )
        try:
            cliente.full_clean()
        except ValidationError:
            continue
        cliente.save()
        criados += 1
    return criados
