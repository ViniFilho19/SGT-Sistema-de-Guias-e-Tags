"""Relatórios em PDF (A4), no mesmo padrão institucional da impressão."""
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .planilha import FUSO, _local, _operador, _situacao, _tipo

AZUL = colors.HexColor("#0B2A5B")
BORDA = colors.HexColor("#B7C3D6")
CLARO = colors.HexColor("#E8EDF5")
ZEBRA = colors.HexColor("#F3F6FA")
LOGO = Path(__file__).parent / "static" / "logo.svg"

S_ORG = ParagraphStyle("org", fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=AZUL)
S_SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#333333"))
S_META = ParagraphStyle("meta", parent=S_SUB, alignment=TA_RIGHT, fontSize=7.5)
S_TIT = ParagraphStyle("tit", fontName="Helvetica-Bold", fontSize=14, leading=17, spaceBefore=6)
S_SEC = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=AZUL, spaceBefore=12,
                       spaceAfter=4)
S_TH = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white)
S_TD = ParagraphStyle("td", fontName="Helvetica", fontSize=7.5, leading=9)
S_TDB = ParagraphStyle("tdb", parent=S_TD, fontName="Helvetica-Bold")
S_ASS = ParagraphStyle("ass", parent=S_TD, alignment=TA_CENTER, fontSize=8, leading=10)


def _p(txt, estilo=S_TD) -> Paragraph:
    t = "" if txt is None else str(txt)
    return Paragraph(escape(t.replace("→", "»")), estilo)


@lru_cache(maxsize=1)
def _logo():
    try:
        from svglib.svglib import svg2rlg
        d = svg2rlg(str(LOGO))
        escala = 14 * mm / d.width
        d.width, d.height = d.width * escala, d.height * escala
        d.scale(escala, escala)
        return d
    except Exception:  # sem logo, o resto do relatório sai normalmente
        return None


class _Canvas(rl_canvas.Canvas):
    """Canvas em duas passagens para escrever 'Página X de Y' no rodapé."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont("Helvetica", 7)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawString(12 * mm, 8 * mm, "SGT · Sistema de Guias e Tags — DETRAN-BA / CTI")
            self.drawRightString(A4[0] - 12 * mm, 8 * mm, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def _cabecalho(titulo: str, sub: str, usuario: str) -> list:
    meta = Paragraph(f"SGT – Sistema de Guias e Tags<br/>Emitido em {datetime.now(FUSO):%d/%m/%Y às %H:%M}<br/>"
                     f"por {escape(usuario)}", S_META)
    org = [Paragraph("DEPARTAMENTO ESTADUAL DE TRÂNSITO DA BAHIA – DETRAN-BA", S_ORG),
           Paragraph("Coordenação de Tecnologia da Informação · Service Desk", S_SUB)]
    logo = _logo()
    larg = A4[0] - 24 * mm
    t = Table([[logo or "", org, meta]], colWidths=[17 * mm, larg - 17 * mm - 52 * mm, 52 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 2, AZUL),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (0, 0), 0)]))
    return [t, Spacer(1, 4), Paragraph(escape(titulo), S_TIT), _p(sub, S_SUB), Spacer(1, 6)]


def _resumo(pares: list[tuple]) -> Table:
    linhas = []
    for i in range(0, len(pares), 2):
        par = list(pares[i:i + 2]) + [("", "")] * (2 - len(pares[i:i + 2]))
        linhas.append([c for r, v in par for c in (_p(r), _p(v, S_TDB))])
    larg = (A4[0] - 24 * mm) / 2
    t = Table(linhas, colWidths=[larg * .64, larg * .36] * 2)
    estilo = [("GRID", (0, 0), (-1, -1), .6, BORDA), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("BACKGROUND", (0, 0), (0, -1), CLARO), ("BACKGROUND", (2, 0), (2, -1), CLARO),
              ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT")]
    t.setStyle(TableStyle(estilo))
    for row in linhas:  # valores alinhados à direita
        for c in (row[1], row[3]):
            c.style = ParagraphStyle("v", parent=S_TDB, alignment=TA_RIGHT)
    return t


def _tabela(cab: list[str], dados: list[list], pesos: list[float], total: list | None = None) -> Table:
    larg = A4[0] - 24 * mm
    soma = sum(pesos)
    linhas = [[_p(h, S_TH) for h in cab]] + [[_p(v) for v in r] for r in dados]
    if not dados:
        linhas.append([_p("Sem registros.")] + [""] * (len(cab) - 1))
    if total:
        linhas.append([_p(v, S_TDB) for v in total])
    t = Table(linhas, colWidths=[larg * p / soma for p in pesos], repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("GRID", (0, 0), (-1, -1), .5, BORDA),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    for i in range(2, len(linhas), 2):
        estilo.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    if total:
        estilo.append(("BACKGROUND", (0, -1), (-1, -1), CLARO))
    if not dados:
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    t.setStyle(TableStyle(estilo))
    return t


def _assinaturas(usuario: str) -> KeepTogether:
    larg = (A4[0] - 24 * mm - 2 * 8 * mm) / 3
    linha = ("LINEABOVE", (0, 0), (0, 0), .8, colors.black)
    t = Table([[Paragraph(f"Responsável pela emissão<br/>{escape(usuario)}", S_ASS), "",
                Paragraph("Conferido por (nome e assinatura)", S_ASS), "", Paragraph("Data ____/____/________", S_ASS)]],
              colWidths=[larg, 8 * mm, larg, 8 * mm, larg])
    t.setStyle(TableStyle([linha, ("LINEABOVE", (2, 0), (2, 0), .8, colors.black),
                           ("LINEABOVE", (4, 0), (4, 0), .8, colors.black)]))
    return KeepTogether([Spacer(1, 28), t])


def _gerar(historia: list, titulo: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=16 * mm, title=titulo, author="SGT – DETRAN-BA")
    doc.build(historia, canvasmaker=_Canvas)
    return buf.getvalue()


def pdf_mes(r: dict, usuario: str) -> bytes:
    titulo = f"Relatório de movimentação – {r['titulo']}"
    h = _cabecalho(titulo, f"Conteúdo: {r['tipo_txt']}", usuario)
    t = r["tot"]
    pares = []
    if r["tipo"] != "etiquetas":
        pares += [("Guias emitidas", t["guias"]), ("Equipamentos movimentados", t["itens"]),
                  ("Guias de entrada", t["entrada"]), ("Guias de saída", t["saida"])]
    if r["tipo"] != "guias":
        pares.append(("Etiquetas geradas", t["etiquetas"]))
    h += [Paragraph("Resumo do período", S_SEC), _resumo(pares)]

    cab, pesos, tot = ["Dia"], [1.2], ["Total"]
    if r["tipo"] != "etiquetas":
        cab += ["Guias de entrada", "Guias de saída", "Equipamentos"]
        pesos += [1, 1, 1]
        tot += [t["entrada"], t["saida"], t["itens"]]
    if r["tipo"] != "guias":
        cab.append("Etiquetas")
        pesos.append(1)
        tot.append(t["etiquetas"])
    dias = [[d["dia"]] + ([d["entrada"], d["saida"], d["itens"]] if r["tipo"] != "etiquetas" else [])
            + ([d["etiquetas"]] if r["tipo"] != "guias" else []) for d in r["tabela"]]
    h += [Paragraph("Movimentação por dia", S_SEC), _tabela(cab, dias, pesos, tot if dias else None)]

    if r["tipo"] != "etiquetas" and r["guias"]:
        dados = [[g.id, _local(g.criado_em), _tipo(g), _situacao(g) or "—", g.chamado or "—",
                  f"{g.remetente} → {g.destinatario}", len(g.itens), _operador(g)] for g in r["guias"]]
        h += [Paragraph("Guias do mês", S_SEC),
              _tabela(["Nº", "Data", "Tipo", "Situação", "Chamado", "Remetente » Destinatário", "Itens", "Operador"],
                      dados, [.55, 1.75, 1.2, 1.05, 1.15, 2.8, .65, 1.75])]
    if r["tipo"] != "guias" and r["etiquetas"]:
        dados = [[_local(e.criado_em), e.foto.hostname or "", e.foto.ip or "", e.foto.patrimonio or "",
                  e.foto.serial or "", e.foto.localidade or "", _operador(e)] for e in r["etiquetas"]]
        h += [Paragraph("Etiquetas do mês", S_SEC),
              _tabela(["Data", "Hostname", "IP", "Patrimônio", "Nº série", "Localidade", "Operador"],
                      dados, [1.45, 1.15, 1.45, 1, 1.5, 1.95, 1.6])]
    h.append(_assinaturas(usuario))
    return _gerar(h, titulo)


def _pares_maquina(hist: dict) -> list[tuple]:
    eq = hist["eq"]
    v = (lambda a: (getattr(eq, a) or "—") if eq else "—")
    return [("Patrimônio", v("patrimonio") if eq else hist["busca"]), ("Nº série", v("serial")),
            ("Hostname", v("hostname")), ("Modelo", v("modelo")), ("IP", v("ip")),
            ("Localidade no cadastro", v("localidade")), ("Onde está agora (última guia)", hist["atual"] or "—"),
            ("Movimentações", f"{len(hist['movs'])} ({hist['saidas']} saídas, {hist['entradas']} entradas)")]


def _linhas_movs(hist: dict) -> list[list]:
    return [[i.data, i.guia.id, _tipo(i.guia), f"{i.guia.remetente} → {i.guia.destinatario}", i.guia.chamado or "—",
             i.hostname or "—", i.guia.entregue_por or "—", i.guia.retirado_por or "—"] for i in hist["movs"]]


CAB_MOVS = ["Data", "Nº", "Tipo", "De » Para", "Chamado", "Hostname", "Entregue por", "Retirado por"]


def pdf_patrimonio(hist: dict, usuario: str) -> bytes:
    titulo = f"Movimentações da máquina {hist['busca']}"
    h = _cabecalho(titulo, "Dados do equipamento e todas as guias de entrada e saída (histórico completo)", usuario)
    h += [Paragraph("Dados do equipamento", S_SEC), _resumo(_pares_maquina(hist))]
    if hist["divergente"]:
        h.append(_p("Atenção: o destino da última guia difere da localidade do cadastro/inventário "
                    "(pode ter havido movimentação sem guia).", S_SUB))
    h += [Paragraph("Movimentações (da mais recente para a mais antiga)", S_SEC),
          _tabela(CAB_MOVS, _linhas_movs(hist), [1.6, .55, 1.25, 3, 1.1, 1.15, 1.3, 1.3])]
    if hist["etiquetas"]:
        dados = [[_local(e.criado_em), e.foto.hostname or "", e.foto.ip or "", e.foto.localidade or "", _operador(e)]
                 for e in hist["etiquetas"]]
        h += [Paragraph("Etiquetas deste equipamento", S_SEC),
              _tabela(["Data", "Hostname", "IP", "Localidade", "Operador"], dados, [1.45, 1.2, 1.45, 2.2, 1.7])]
    h.append(_assinaturas(usuario))
    return _gerar(h, titulo)
