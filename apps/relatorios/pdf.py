"""Relatório de pagamentos em PDF (ReportLab/Platypus).

Retrato A4, paleta do site (azul de marca, vermelho só para o que está em
atraso), cartões com os números-chave, tabelas com respiro e total, rodapé com
"Página X de Y". Só fontes padrão do PDF (Helvetica) — cobre o português e não
depende de arquivo de fonte no servidor.
"""

from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

AZUL = colors.HexColor("#1F5FD1")
AZUL_FUNDO = colors.HexColor("#EAF1FD")
TINTA = colors.HexColor("#111827")
TINTA_SUAVE = colors.HexColor("#4B5563")
TINTA_FRACA = colors.HexColor("#6B7280")
LINHA = colors.HexColor("#E5E7EB")
LINHA_FORTE = colors.HexColor("#D1D5DB")
CARTAO = colors.HexColor("#F3F4F6")
VERMELHO = colors.HexColor("#C92A3A")
VERDE = colors.HexColor("#1A7F4B")
AMBAR = colors.HexColor("#D97706")

LARGURA_PAGINA, ALTURA_PAGINA = A4
MARGEM = 15 * mm
LARGURA = LARGURA_PAGINA - 2 * MARGEM  # 180 mm

_BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=11, textColor=TINTA)
ESTILOS = {
    "texto": _BASE,
    "direita": ParagraphStyle("direita", parent=_BASE, alignment=TA_RIGHT),
    "direita_negrito": ParagraphStyle(
        "direita_negrito", parent=_BASE, alignment=TA_RIGHT, fontName="Helvetica-Bold"
    ),
    "negrito": ParagraphStyle("negrito", parent=_BASE, fontName="Helvetica-Bold"),
    "critico": ParagraphStyle(
        "critico", parent=_BASE, alignment=TA_RIGHT, textColor=VERMELHO, fontName="Helvetica-Bold"
    ),
    "cabecalho": ParagraphStyle(
        "cabecalho", parent=_BASE, fontName="Helvetica-Bold", fontSize=7.5, leading=9,
        textColor=TINTA_FRACA,
    ),
    "cabecalho_direita": ParagraphStyle(
        "cabecalho_direita", parent=_BASE, fontName="Helvetica-Bold", fontSize=7.5, leading=9,
        textColor=TINTA_FRACA, alignment=TA_RIGHT,
    ),
    "vazio": ParagraphStyle(
        "vazio", parent=_BASE, textColor=TINTA_FRACA, fontName="Helvetica-Oblique"
    ),
    "secao": ParagraphStyle(
        "secao", parent=_BASE, fontName="Helvetica-Bold", fontSize=11, leading=14,
        spaceBefore=14, spaceAfter=5,
    ),
    "secao_nota": ParagraphStyle(
        "secao_nota", parent=_BASE, fontSize=8, textColor=TINTA_FRACA, spaceAfter=5,
    ),
    "cartao_rotulo": ParagraphStyle(
        "cartao_rotulo", parent=_BASE, fontSize=7.5, leading=9, textColor=TINTA_FRACA,
    ),
    "cartao_valor": ParagraphStyle(
        "cartao_valor", parent=_BASE, fontName="Helvetica-Bold", fontSize=15, leading=18,
    ),
    "cartao_valor_critico": ParagraphStyle(
        "cartao_valor_critico", parent=_BASE, fontName="Helvetica-Bold", fontSize=15,
        leading=18, textColor=VERMELHO,
    ),
    "faixa_titulo": ParagraphStyle(
        "faixa_titulo", parent=_BASE, fontName="Helvetica-Bold", fontSize=20, leading=24,
        textColor=colors.white,
    ),
    "faixa_periodo": ParagraphStyle(
        "faixa_periodo", parent=_BASE, fontSize=10.5, leading=14,
        textColor=colors.HexColor("#DCE8FC"),
    ),
    "faixa_meta": ParagraphStyle(
        "faixa_meta", parent=_BASE, fontSize=8, leading=11, alignment=TA_RIGHT,
        textColor=colors.HexColor("#DCE8FC"),
    ),
}


def _reais(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _p(texto, estilo="texto"):
    """Parágrafo com o texto escapado (nome de cliente pode ter & ou <)."""
    return Paragraph(escape(str(texto)), ESTILOS[estilo])


def _percentual(parte, total):
    if not total:
        return "—"
    return f"{parte / total * 100:.0f}%".replace(".", ",")


def _faixa_titulo(relatorio, gerado_por):
    agora = timezone.localtime()
    meta = f"Gerado em {agora:%d/%m/%Y às %H:%M}"
    if gerado_por:
        meta += f"<br/>por {escape(gerado_por)}"
    periodo = (
        f"{relatorio['inicio']:%d/%m/%Y}"
        if relatorio["inicio"] == relatorio["fim"]
        else f"{relatorio['inicio']:%d/%m/%Y} a {relatorio['fim']:%d/%m/%Y}"
    )
    esquerda = [
        Paragraph("Relatório de pagamentos", ESTILOS["faixa_titulo"]),
        Paragraph(f"Período: {periodo}", ESTILOS["faixa_periodo"]),
    ]
    direita = Paragraph(meta, ESTILOS["faixa_meta"])
    tabela = Table([[esquerda, direita]], colWidths=[LARGURA * 0.65, LARGURA * 0.35])
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), AZUL),
                ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
                ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 6 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6 * mm),
            ]
        )
    )
    return tabela


def _cartoes(itens):
    """Grade de cartões 4 por linha. ``itens``: (rótulo, valor, crítico?)."""
    folga = 3 * mm
    largura = (LARGURA - 3 * folga) / 4
    linhas, estilo = [], [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for r in range(0, len(itens), 4):
        linha = []
        for i, (rotulo, valor, critico) in enumerate(itens[r : r + 4]):
            celula = Table(
                [
                    [Paragraph(escape(rotulo), ESTILOS["cartao_rotulo"])],
                    [
                        Paragraph(
                            escape(valor),
                            ESTILOS["cartao_valor_critico" if critico else "cartao_valor"],
                        )
                    ],
                ],
                colWidths=[largura],
            )
            celula.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), CARTAO),
                        ("LINEBEFORE", (0, 0), (0, -1), 2, VERMELHO if critico else AZUL),
                        ("LEFTPADDING", (0, 0), (-1, -1), 3.5 * mm),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                        ("TOPPADDING", (0, 0), (-1, 0), 2.5 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
                        ("TOPPADDING", (0, 1), (-1, 1), 1 * mm),
                        ("BOTTOMPADDING", (0, 1), (-1, 1), 2.5 * mm),
                    ]
                )
            )
            linha.append(celula)
            if i < 3:
                linha.append("")
        linhas.append(linha)
        if r + 4 < len(itens):
            linhas.append([""] * 7)
    larguras = [largura, folga, largura, folga, largura, folga, largura]
    tabela = Table(linhas, colWidths=larguras)
    for n, linha in enumerate(linhas):
        if linha == [""] * 7:
            estilo.append(("ROWBACKGROUNDS", (0, n), (-1, n), [colors.white]))
            estilo.append(("TOPPADDING", (0, n), (-1, n), 1.5 * mm))
    tabela.setStyle(TableStyle(estilo))
    return tabela


def _tabela(cabecalho, linhas, larguras, direita, total=None, vazio="", critica=None):
    """Tabela de dados. ``direita``: índices de colunas alinhadas à direita;
    ``critica``: índice da coluna em vermelho (valores em atraso)."""
    dados = [
        [
            _p(titulo, "cabecalho_direita" if i in direita else "cabecalho")
            for i, titulo in enumerate(cabecalho)
        ]
    ]
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, AZUL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINHA),
    ]
    if not linhas:
        dados.append([_p(vazio, "vazio")] + [""] * (len(cabecalho) - 1))
        estilo.append(("SPAN", (0, 1), (-1, 1)))
        estilo.append(("BACKGROUND", (0, 1), (-1, 1), CARTAO))
        estilo.append(("TOPPADDING", (0, 1), (-1, 1), 8))
        estilo.append(("BOTTOMPADDING", (0, 1), (-1, 1), 8))
    for linha in linhas:
        dados.append(
            [
                _p(
                    valor,
                    ("critico" if i == critica else "direita") if i in direita else "texto",
                )
                for i, valor in enumerate(linha)
            ]
        )
    if total and linhas:
        dados.append(
            [_p(v, "direita_negrito" if i in direita else "negrito") for i, v in enumerate(total)]
        )
        n = len(dados) - 1
        estilo.append(("LINEABOVE", (0, n), (-1, n), 1, LINHA_FORTE))
        estilo.append(("LINEBELOW", (0, n), (-1, n), 0, colors.white))
        estilo.append(("BACKGROUND", (0, n), (-1, n), AZUL_FUNDO))
    tabela = Table(dados, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle(estilo))
    return tabela


def _composicao(relatorio):
    """Barra empilhada + legenda: de onde veio o dinheiro recebido."""
    total = relatorio["total_recebido"]
    partes = [
        ("Parcelas do período", relatorio["recebido_do_periodo"], AZUL),
        ("Parcelas atrasadas", relatorio["recebido_de_atrasadas"], AMBAR),
        ("Adiantado", relatorio["recebido_adiantado"], VERDE),
    ]
    if relatorio["recebido_sem_parcela"]:
        partes.append(("Sem parcela", relatorio["recebido_sem_parcela"], TINTA_FRACA))

    largura = 88 * mm
    linhas = [[_p("Origem", "cabecalho"), _p("Valor", "cabecalho_direita"), _p("%", "cabecalho_direita")]]
    for rotulo, valor, _cor in partes:
        linhas.append([_p(rotulo), _p(_reais(valor), "direita"), _p(_percentual(valor, total), "direita")])
    tabela = Table(linhas, colWidths=[largura - 40 * mm - 12 * mm, 40 * mm, 12 * mm])
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, AZUL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINHA),
    ]
    tabela.setStyle(TableStyle(estilo))

    # Barra: uma linha de células coloridas proporcionais ao valor.
    barra = None
    if total and total > 0:
        larguras = [float(v / total) * largura for _r, v, _c in partes if v > 0]
        cores = [c for _r, v, c in partes if v > 0]
        barra = Table([[""] * len(larguras)], colWidths=larguras, rowHeights=[3 * mm])
        barra.setStyle(
            TableStyle(
                [("BACKGROUND", (i, 0), (i, 0), cor) for i, cor in enumerate(cores)]
                + [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
    conteudo = [_p("Composição do recebido", "negrito"), Spacer(1, 2 * mm)]
    if barra is not None:
        conteudo += [barra, Spacer(1, 2 * mm)]
    conteudo.append(tabela)
    conteudo.append(Spacer(1, 1.5 * mm))
    conteudo.append(
        Paragraph(
            f"Falta receber do período: <b>{_reais(relatorio['falta_do_periodo'])}</b>",
            ESTILOS["secao_nota"],
        )
    )
    return conteudo


def _por_forma(relatorio):
    largura = 88 * mm
    linhas = [
        [_p("Forma", "cabecalho"), _p("Pagamentos", "cabecalho_direita"), _p("Total", "cabecalho_direita")]
    ]
    for linha in relatorio["por_forma"]:
        linhas.append(
            [
                _p(linha["forma_label"]),
                _p(linha["quantidade"], "direita"),
                _p(_reais(linha["total"]), "direita"),
            ]
        )
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, AZUL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINHA),
    ]
    if not relatorio["por_forma"]:
        linhas.append([_p("Nenhum recebimento no período.", "vazio"), "", ""])
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    tabela = Table(linhas, colWidths=[largura - 45 * mm, 22 * mm, 23 * mm])
    tabela.setStyle(TableStyle(estilo))
    return [_p("Recebido por forma de pagamento", "negrito"), Spacer(1, 2 * mm), tabela]


def _lado_a_lado(esquerda, direita):
    tabela = Table([[esquerda, "", direita]], colWidths=[88 * mm, 4 * mm, 88 * mm])
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tabela


class _CanvasNumerado(pdfcanvas.Canvas):
    """Canvas que sabe o total de páginas, para "Página X de Y"."""

    def __init__(self, *args, titulo_rodape="", **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []
        self._titulo_rodape = titulo_rodape

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self._decorar(total)
            super().showPage()
        super().save()

    def _decorar(self, total):
        self.saveState()
        pagina = self._pageNumber
        if pagina > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(AZUL)
            self.drawString(MARGEM, ALTURA_PAGINA - 10 * mm, "Relatório de pagamentos")
            self.setFont("Helvetica", 8)
            self.setFillColor(TINTA_FRACA)
            self.drawRightString(LARGURA_PAGINA - MARGEM, ALTURA_PAGINA - 10 * mm, self._titulo_rodape)
            self.setStrokeColor(LINHA)
            self.setLineWidth(0.5)
            self.line(MARGEM, ALTURA_PAGINA - 12 * mm, LARGURA_PAGINA - MARGEM, ALTURA_PAGINA - 12 * mm)
        self.setStrokeColor(LINHA)
        self.setLineWidth(0.5)
        self.line(MARGEM, 13 * mm, LARGURA_PAGINA - MARGEM, 13 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(TINTA_FRACA)
        self.drawString(MARGEM, 9 * mm, "Acompanhamento de pagamentos de celulares")
        self.drawRightString(LARGURA_PAGINA - MARGEM, 9 * mm, f"Página {pagina} de {total}")
        self.restoreState()


def montar_pdf(arquivo, relatorio, gerado_por=""):
    """Escreve o relatório de ``relatorio`` (ver ``servicos.montar_relatorio``)
    em ``arquivo`` (qualquer objeto com ``write``)."""
    inicio, fim = relatorio["inicio"], relatorio["fim"]
    periodo = f"{inicio:%d/%m/%Y}" if inicio == fim else f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
    documento = SimpleDocTemplate(
        arquivo,
        pagesize=A4,
        leftMargin=MARGEM,
        rightMargin=MARGEM,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Relatório de pagamentos — {periodo}",
        author="Acompanhamento de pagamentos",
    )

    itens = [_faixa_titulo(relatorio, gerado_por), Spacer(1, 6 * mm)]

    itens.append(
        _cartoes(
            [
                ("Previsto no período", _reais(relatorio["total_previsto"]), False),
                ("Recebido no período", _reais(relatorio["total_recebido"]), False),
                ("Juros recebidos", _reais(relatorio["total_juros"]), False),
                ("Total em atraso", _reais(relatorio["total_atrasado"]), True),
                ("Pagamentos registrados", str(relatorio["quantidade_recebimentos"]), False),
                ("Parcelas atrasadas", str(relatorio["quantidade_atrasados"]), False),
                ("Novos clientes", str(relatorio["novos_clientes"]), False),
                ("Contratos quitados", str(relatorio["contratos_quitados"]), False),
            ]
        )
    )
    itens.append(Spacer(1, 7 * mm))
    itens.append(_lado_a_lado(_composicao(relatorio), _por_forma(relatorio)))

    # Recebimentos
    recebimentos = relatorio["recebimentos"]
    itens.append(
        KeepTogether(
            [
                Paragraph("Recebimentos", ESTILOS["secao"]),
                Paragraph(
                    f"{len(recebimentos)} pagamento(s) registrado(s) entre {periodo}.",
                    ESTILOS["secao_nota"],
                ),
            ]
        )
    )
    itens.append(
        _tabela(
            ["Data", "Cliente", "Contrato", "Parcela", "Forma", "Valor"],
            [
                [
                    p.data_pagamento.strftime("%d/%m/%Y"),
                    p.contrato.cliente.nome,
                    p.contrato.apelido,
                    p.vencimento.numero if p.vencimento else "—",
                    p.get_forma_display(),
                    _reais(p.valor_pago),
                ]
                for p in recebimentos
            ],
            [22 * mm, 55 * mm, 38 * mm, 14 * mm, 20 * mm, 31 * mm],
            direita={3, 5},
            total=[
                "Total",
                "",
                "",
                "",
                "",
                _reais(relatorio["total_recebido"]),
            ],
            vazio="Nenhum recebimento no período.",
        )
    )

    # Atrasos
    atrasados = relatorio["atrasados"]
    itens.append(
        KeepTogether(
            [
                Paragraph("Parcelas em atraso", ESTILOS["secao"]),
                Paragraph(
                    f"Situação ao fim do período ({fim:%d/%m/%Y}): "
                    f"{len(atrasados)} parcela(s) vencida(s) e sem baixa.",
                    ESTILOS["secao_nota"],
                ),
            ]
        )
    )
    itens.append(
        _tabela(
            ["Cliente", "Contrato", "Vencimento", "Parcela", "Atraso", "Em aberto"],
            [
                [
                    v.contrato.cliente.nome,
                    v.contrato.apelido,
                    v.data_vencimento.strftime("%d/%m/%Y"),
                    v.numero,
                    f"{v.dias_atraso_relatorio} d",
                    _reais(v.valor_em_aberto),
                ]
                for v in atrasados
            ],
            [52 * mm, 38 * mm, 23 * mm, 14 * mm, 17 * mm, 36 * mm],
            direita={3, 4, 5},
            total=["Total em atraso", "", "", "", "", _reais(relatorio["total_atrasado"])],
            vazio="Nenhuma parcela em atraso.",
            critica=5,
        )
    )

    documento.build(
        itens,
        canvasmaker=lambda *a, **k: _CanvasNumerado(*a, titulo_rodape=periodo, **k),
    )
