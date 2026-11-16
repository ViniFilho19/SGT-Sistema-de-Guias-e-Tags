"""Relatórios em planilha Excel (.xlsx), com cabeçalho institucional e tabelas formatadas."""
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FUSO = ZoneInfo("America/Bahia")
AZUL = "0B2A5B"
FINA = Side(style="thin", color="B7C3D6")
BORDA = Border(left=FINA, right=FINA, top=FINA, bottom=FINA)
CAB_FILL = PatternFill("solid", fgColor=AZUL)
TOT_FILL = PatternFill("solid", fgColor="E8EDF5")
ZEBRA = PatternFill("solid", fgColor="F6F8FB")


def _tipo(g) -> str:
    base = "Entrada" if "ENTRADA" in g.tipo else "Saída"
    return f"{base} - {g.tipo.split(' - ', 1)[1].capitalize()}" if " - " in g.tipo else base


def _situacao(g) -> str:
    if "ENTRADA" in g.tipo:
        return ""
    return "Entregue" if g.status == "entregue" else "Pronta p/ entrega"


def _operador(o) -> str:
    return o.operador_original or (o.operador.nome if o.operador else "")


def _local(dt) -> str:
    from datetime import timezone
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(FUSO).strftime("%d/%m/%Y %H:%M")


def _cabecalho(ws, titulo: str, subtitulo: str, usuario: str, ncols: int) -> int:
    """Escreve o cabeçalho institucional e devolve a próxima linha livre."""
    linhas = [("DEPARTAMENTO ESTADUAL DE TRÂNSITO DA BAHIA – DETRAN-BA", Font(bold=True, size=12, color=AZUL)),
              ("Coordenação de Tecnologia da Informação · Service Desk", Font(size=10, color="44546A")),
              (titulo, Font(bold=True, size=14, color="000000")),
              (subtitulo, Font(size=10, color="44546A")),
              (f"Emitido em {datetime.now(FUSO):%d/%m/%Y às %H:%M} por {usuario} · SGT – Sistema de Guias e Tags",
               Font(italic=True, size=9, color="6B7280"))]
    ultima = get_column_letter(max(ncols, 1))
    for i, (txt, fonte) in enumerate(linhas, start=1):
        ws.merge_cells(f"A{i}:{ultima}{i}")
        c = ws[f"A{i}"]
        c.value, c.font = txt, fonte
        c.alignment = Alignment(vertical="center")
    ws.row_dimensions[3].height = 22
    return len(linhas) + 2


def _tabela(ws, linha: int, cabecalhos: list[str], dados: list[list], larguras: list[int],
            total: list | None = None) -> int:
    for j, (h, w) in enumerate(zip(cabecalhos, larguras), start=1):
        c = ws.cell(linha, j, h)
        c.font, c.fill, c.border = Font(bold=True, color="FFFFFF"), CAB_FILL, BORDA
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = max(ws.column_dimensions[get_column_letter(j)].width or 0, w)
    ws.row_dimensions[linha].height = 20
    inicio = linha
    for i, valores in enumerate(dados, start=1):
        for j, v in enumerate(valores, start=1):
            c = ws.cell(linha + i, j, v)
            c.border = BORDA
            c.alignment = Alignment(vertical="top", wrap_text=True)
            if i % 2 == 0:
                c.fill = ZEBRA
    fim = linha + len(dados)
    if not dados:
        fim += 1
        ws.cell(fim, 1, "Sem registros.").font = Font(italic=True, color="6B7280")
    if dados:
        ws.auto_filter.ref = f"A{inicio}:{get_column_letter(len(cabecalhos))}{fim}" if not ws.auto_filter.ref else ws.auto_filter.ref
    if total:
        fim += 1
        for j, v in enumerate(total, start=1):
            c = ws.cell(fim, j, v)
            c.font, c.fill, c.border = Font(bold=True), TOT_FILL, BORDA
    return fim + 2


def _aba(wb, nome: str, titulo: str, subtitulo: str, usuario: str, cab: list[str], dados: list[list],
         larguras: list[int], total=None, primeira=False):
    ws = wb.active if primeira else wb.create_sheet()
    ws.title = nome
    linha = _cabecalho(ws, titulo, subtitulo, usuario, len(cab))
    _tabela(ws, linha, cab, dados, larguras, total)
    ws.freeze_panes = ws.cell(linha + 1, 1)
    ws.print_title_rows = f"{linha}:{linha}"
    ws.page_setup.orientation = "landscape" if len(cab) > 6 else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.oddFooter.right.text = "Página &P de &N"
    ws.oddFooter.left.text = "SGT – DETRAN-BA"
    return ws


def _linhas_guias(guias) -> list[list]:
    return [[g.id, _local(g.criado_em), _tipo(g), _situacao(g), g.chamado or "", g.remetente or "",
             g.destinatario or "", len(g.itens), g.retirado_por or "", _operador(g)] for g in guias]


CAB_GUIAS = ["Nº", "Data", "Tipo", "Situação", "Chamado", "Remetente", "Destinatário", "Itens", "Retirado por", "Operador"]
LARG_GUIAS = [7, 17, 24, 18, 14, 30, 30, 8, 24, 24]
CAB_ITENS = ["Guia nº", "Data", "Tipo da guia", "Equipamento", "Modelo", "Patrimônio", "Nº série", "Hostname", "IP"]
LARG_ITENS = [9, 17, 24, 14, 20, 14, 20, 16, 15]
CAB_ETQ = ["Data", "Hostname", "IP", "Patrimônio", "Nº série", "Localidade", "Operador"]
LARG_ETQ = [17, 16, 15, 14, 20, 34, 24]


def _linhas_etiquetas(etqs) -> list[list]:
    return [[_local(e.criado_em), e.foto.hostname or "", e.foto.ip or "", e.foto.patrimonio or "",
             e.foto.serial or "", e.foto.localidade or "", _operador(e)] for e in etqs]


def _salvar(wb) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def planilha_mes(r: dict, usuario: str) -> bytes:
    wb = Workbook()
    titulo = f"Relatório de movimentação – {r['titulo']}"
    sub = f"Conteúdo: {r['tipo_txt']}"
    t = r["tot"]
    resumo = []
    if r["tipo"] != "etiquetas":
        resumo += [["Guias emitidas", t["guias"]], ["Guias de entrada", t["entrada"]], ["Guias de saída", t["saida"]],
                   ["Equipamentos movimentados", t["itens"]]]
    if r["tipo"] != "guias":
        resumo.append(["Etiquetas geradas", t["etiquetas"]])
    ws = _aba(wb, "Resumo", titulo, sub, usuario, ["Indicador", "Quantidade"], resumo, [34, 14], primeira=True)

    dias = [[d["dia"], d["entrada"], d["saida"], d["itens"], d["etiquetas"]] for d in r["tabela"]]
    _aba(wb, "Por dia", titulo, sub, usuario, ["Dia", "Guias de entrada", "Guias de saída", "Equipamentos", "Etiquetas"],
         dias, [14, 16, 16, 16, 12], total=["Total", t["entrada"], t["saida"], t["itens"], t["etiquetas"]])
    if r["tipo"] != "etiquetas":
        _aba(wb, "Guias", titulo, sub, usuario, CAB_GUIAS, _linhas_guias(r["guias"]), LARG_GUIAS)
        itens = [[g.id, _local(g.criado_em), _tipo(g), i.tipo_equipamento, i.modelo or "", i.patrimonio or "",
                  i.serial or "", i.hostname or "", i.ip or ""] for g in r["guias"] for i in g.itens]
        _aba(wb, "Equipamentos", titulo, sub, usuario, CAB_ITENS, itens, LARG_ITENS)
    if r["tipo"] != "guias":
        _aba(wb, "Etiquetas", titulo, sub, usuario, CAB_ETQ, _linhas_etiquetas(r["etiquetas"]), LARG_ETQ)
    return _salvar(wb)


def planilha_patrimonio(h: dict, usuario: str) -> bytes:
    from .pdf import CAB_MOVS, _linhas_movs, _pares_maquina
    wb = Workbook()
    titulo = f"Movimentações da máquina {h['busca']}"
    sub = "Dados do equipamento e todas as guias de entrada e saída (histórico completo)"
    dados = [list(par) for par in _pares_maquina(h)]
    if h["divergente"]:
        dados.append(["Atenção", "Destino da última guia difere da localidade do cadastro/inventário"])
    _aba(wb, "Equipamento", titulo, sub, usuario, ["Informação", "Valor"], dados, [30, 50], primeira=True)
    movs = [[str(c).replace("→", "->") if j == 3 else c for j, c in enumerate(r)] for r in _linhas_movs(h)]
    _aba(wb, "Movimentações", titulo, sub, usuario, [c.replace("»", "->") for c in CAB_MOVS], movs,
         [17, 7, 24, 50, 14, 16, 24, 24])
    _aba(wb, "Etiquetas", titulo, sub, usuario, CAB_ETQ, _linhas_etiquetas(h["etiquetas"]), LARG_ETQ)
    return _salvar(wb)
