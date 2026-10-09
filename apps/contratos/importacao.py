"""Leitura segura da planilha de contratos, sem persistir nenhum dado."""

import csv
import datetime
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from io import TextIOWrapper

from openpyxl import load_workbook

from .models import Contrato


_COLUNAS = {
    "cliente": "cliente", "contato": "telefone", "cpf": "cpf", "cpfs": "cpf",
    "modelo": "modelo", "imei": "imei", "emei": "imei", "datadacompra": "data_inicio", "frequenciadepagamento": "estrutura",
    "parcelaatual": "parcela_atual", "totaldeparcelas": "num_parcelas",
    "vencimentodaparcela": "proximo_vencimento", "valordaparcela": "valor_parcela",
    "jurosdiario": "juros_diario", "pagouhoje": "pagou_hoje", "status": "status",
    "observacoes": "observacoes",
    "diadecobranca": "dia_cobranca", "diacobranca": "dia_cobranca", "diasdecobranca": "dia_cobranca",
}
_FREQUENCIA = re.compile(r"^(semanal|quinzenal|mensal)(?:\s*[-–]\s*(\d{1,2}))?$")
_DOIS_DIAS = re.compile(r"dias?\s*(\d{1,2})\s*(?:e|/|,|&)\s*(\d{1,2})")
# Frequências que deixaram de existir: a linha é recusada com um motivo claro.
_ESTRUTURAS_REMOVIDAS = {"diário", "diario", "diária", "diaria", "por dezena", "dezena"}


def _texto(valor):
    return str(valor or "").strip()


def _frequencia(valor):
    """``"Mensal - 15"`` → ``("mensal", 15)``; ``"Semanal"`` → ``("semanal", None)``; senão ``(None, None)``."""
    acho = _FREQUENCIA.match(re.sub(r"\s+", " ", _texto(valor).lower()))
    if not acho:
        return None, None
    return acho.group(1), int(acho.group(2)) if acho.group(2) else None


def _dia_de_cobranca(estrutura, sufixo, vencimento, texto_livre):
    """Dias do mês da cobrança (``"5,20"`` / ``"15"`` / ``""``) e avisos sobre a planilha.

    O calendário nasce do **vencimento da parcela**: semanal e quinzenal seguem o dia da semana
    dele, mensal o dia do mês. O número depois de "Mensal -" costuma ser só um agrupamento da
    planilha, então não manda: se divergir do vencimento, vale o vencimento e o aviso aparece.
    """
    avisos = []
    if estrutura == "mensal":
        if sufixo and sufixo != vencimento.day:
            avisos.append(f"A planilha diz “Mensal - {sufixo}”, mas o vencimento é dia {vencimento.day}: a cobrança ficou no dia {vencimento.day}.")
        return str(vencimento.day), avisos
    if estrutura == "quinzenal":
        acho = _DOIS_DIAS.search(texto_livre.lower())
        if acho:
            dias = sorted({int(acho.group(1)), int(acho.group(2))})
            if len(dias) == 2 and all(1 <= d <= 31 for d in dias):
                if vencimento.day not in dias:
                    avisos.append(f"A planilha diz “dias {dias[0]} e {dias[1]}”, mas o vencimento é dia {vencimento.day}: confira o calendário.")
                return ",".join(str(d) for d in dias), avisos
    return "", avisos


def _cabecalho(valor):
    """Normaliza espaços/quebras de linha que o Excel mantém em títulos."""
    texto = unicodedata.normalize("NFKD", _texto(valor)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def _decimal(valor):
    texto = _texto(valor).replace("R$", "").replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    return Decimal(texto)


def _data(valor):
    if isinstance(valor, (datetime.datetime, datetime.date)):
        return valor.date() if isinstance(valor, datetime.datetime) else valor
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(_texto(valor), formato).date()
        except ValueError:
            pass
    raise ValueError("data inválida")


def _linhas(arquivo):
    nome = arquivo.name.lower()
    if nome.endswith(".csv"):
        texto = TextIOWrapper(arquivo.file, encoding="utf-8-sig")
        amostra = texto.read(4096)
        texto.seek(0)
        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=";,")
        except csv.Error:
            dialeto = csv.excel
        return list(csv.reader(texto, dialect=dialeto))
    livro = load_workbook(arquivo, read_only=True, data_only=True)
    for aba in livro.worksheets:
        linhas = list(aba.iter_rows(values_only=True))
        for indice, linha in enumerate(linhas):
            chaves = {_COLUNAS.get(_cabecalho(c), "") for c in linha}
            if {"cliente", "modelo"}.issubset(chaves):
                return linhas[indice:]
    return []


def analisar(arquivo):
    """Devolve uma prévia de linhas válidas/inválidas; nunca escreve no banco."""
    linhas = _linhas(arquivo)
    if not linhas:
        return [], ["A planilha está vazia."]
    cabecalho = [_COLUNAS.get(_cabecalho(c), "") for c in linhas[0]]
    faltam = {"cliente", "modelo", "data_inicio", "estrutura", "num_parcelas", "valor_parcela", "proximo_vencimento"} - set(cabecalho)
    if faltam:
        return [], ["Colunas obrigatórias ausentes: " + ", ".join(sorted(faltam)) + "."]
    resultado = []
    for numero, valores in enumerate(linhas[1:], start=2):
        if not any(valor not in (None, "") for valor in valores):
            continue
        bruto = {cabecalho[i]: valores[i] for i in range(min(len(cabecalho), len(valores))) if cabecalho[i]}
        erros = []
        try:
            estrutura, sufixo_mensal = _frequencia(bruto.get("estrutura"))
            if not estrutura:
                if _texto(bruto.get("estrutura")).lower() in _ESTRUTURAS_REMOVIDAS:
                    resultado.append({"linha": numero, "erros": [
                        "Frequência não aceita: o sistema trabalha só com semanal, quinzenal e mensal."]})
                    continue
                raise ValueError("frequência não reconhecida")
            imei_bruto = re.sub(r"\D", "", _texto(bruto.get("imei")))
            imei = imei_bruto if len(imei_bruto) == 15 else ""
            alerta_imei = (
                [] if imei else
                ["IMEI inválido (devem ser 15 dígitos): o contrato ficará sem vínculo com o estoque."] if imei_bruto else
                ["IMEI ausente: o contrato ficará sem vínculo com o estoque."]
            )
            vencimento = _data(bruto.get("proximo_vencimento"))
            dias_mes, avisos_dia = _dia_de_cobranca(
                estrutura, sufixo_mensal, vencimento,
                f"{_texto(bruto.get('dia_cobranca'))} {_texto(bruto.get('observacoes'))}",
            )
            try:
                parcela_atual = max(0, int(float(str(bruto.get("parcela_atual")).replace(",", ".")))) if bruto.get("parcela_atual") not in (None, "") else 0
            except ValueError:
                parcela_atual = 0
            resultado.append({
                "linha": numero, "cliente": _texto(bruto.get("cliente")), "modelo": _texto(bruto.get("modelo")),
                "imei": imei,
                "cpf": re.sub(r"\D", "", _texto(bruto.get("cpf"))), "telefone": re.sub(r"\D", "", _texto(bruto.get("telefone"))),
                "estrutura": estrutura, "inicio": _data(bruto.get("data_inicio")),
                "vencimento": vencimento, "dias_mes": dias_mes, "parcela_atual": parcela_atual,
                "parcelas": int(bruto.get("num_parcelas")), "valor": _decimal(bruto.get("valor_parcela")),
                "juros": _decimal(bruto.get("juros_diario")) if bruto.get("juros_diario") not in (None, "") else Decimal("5.00"),
                "observacoes": _texto(bruto.get("observacoes")),
                "alertas": (["CPF ou telefone ausente nesta linha."] if not _texto(bruto.get("cpf")) or not _texto(bruto.get("telefone")) else []) + alerta_imei + ["Confirme o valor total financiado antes de importar."] +
                    avisos_dia +
                    (["Confira a quantidade de parcelas já pagas (a planilha informa a última parcela paga)."] if bruto.get("parcela_atual") not in (None, "") else []),
            })
        except (ValueError, InvalidOperation, TypeError):
            erros.append("Revise data, frequência, quantidade de parcelas e valores.")
            resultado.append({"linha": numero, "erros": erros})
    return resultado, []


def chave_cliente(linha):
    """Identifica o cliente de uma linha: CPF, senão telefone, senão o nome.

    A planilha tem uma linha por contrato, então o mesmo cliente aparece mais de
    uma vez (vários aparelhos). Nome sozinho é o último recurso: dois "Gabriel"
    com telefones diferentes continuam sendo duas pessoas.
    """
    cpf = linha.get("cpf") or ""
    telefone = linha.get("telefone") or ""
    nome = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", linha.get("cliente") or "").encode("ascii", "ignore").decode().lower()).strip()
    return cpf or telefone or nome


def contar_por_cliente(linhas):
    """Marca cada linha válida com quantos contratos o mesmo cliente tem na planilha.

    Devolve ``(clientes_distintos, linhas_validas)``.
    """
    validas = [linha for linha in linhas if not linha.get("erros")]
    contagem = {}
    for linha in validas:
        contagem[chave_cliente(linha)] = contagem.get(chave_cliente(linha), 0) + 1
    for linha in validas:
        linha["contratos_do_cliente"] = contagem[chave_cliente(linha)]
    return len(contagem), len(validas)
