"""Almoxarifado: catálogo de peças e insumos de TI, saldo, entradas (com nota fiscal) e saídas (por chamado).

Papéis: qualquer usuário consulta e registra entrada/saída avulsa; "bancada" e "admin" gerenciam o catálogo,
as categorias e a entrada em lote com nota fiscal.
"""
import math
import re
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .config import PASTA_DADOS
from .database import get_db
from .models import CategoriaPeca, NotaFiscal, Peca, PecaMovimento, User, agora
from .routers.guias import equipamento_por_patrimonio
from .web import hora_local, pagina, templates, usuario_web

router = APIRouter(include_in_schema=False)
PASTA_NF = PASTA_DADOS / "notasfiscais"
MAX_PDF = 10 * 1024 * 1024  # 10 MB
POR_PAGINA = 50
POR_PAGINA_EXTRATO = 20
GESTORES = ("admin", "bancada")
SITUACOES = {"esgotado": ("Esgotado", "b-red"), "baixo": ("Baixo", "b-orange"), "ok": ("OK", "b-green")}
AVISOS = {"peca": "Peça cadastrada no catálogo.", "editada": "Peça atualizada.", "excluida": "Peça excluída.",
          "categoria": "Categoria criada.", "cat_excluida": "Categoria excluída.",
          "entrada": "Entrada registrada.", "saida": "Saída registrada.", "lote": "Entrada em lote registrada."}
ERROS = {"cat_em_uso": "Essa categoria tem peças cadastradas; mude a categoria delas antes de excluir.",
         "cat_nome": "Informe o nome da categoria (até 50 caracteres).",
         "cat_existe": "Já existe uma categoria com esse nome."}


class Invalido(Exception):
    """Erro de validação com mensagem para o usuário."""


def pode_gerir(user: User) -> bool:
    return user.papel in GESTORES


def gestor_web(user: User = Depends(usuario_web)) -> User:
    if not pode_gerir(user):
        raise HTTPException(403, "Apenas a bancada ou administradores")
    return user


templates.env.globals["pode_gerir"] = pode_gerir
templates.env.globals["SITUACOES"] = SITUACOES


# ---------- validação ----------
def maiusc(txt: str, tam: int, rotulo: str, obrigatorio: bool = False) -> Optional[str]:
    t = " ".join((txt or "").split()).upper()
    if obrigatorio and not t:
        raise Invalido(f"Informe {rotulo}.")
    if len(t) > tam:
        raise Invalido(f"{rotulo[0].upper() + rotulo[1:]}: até {tam} caracteres.")
    return t or None


def texto(txt: str, tam: int, rotulo: str, obrigatorio: bool = False) -> Optional[str]:
    t = (txt or "").strip()
    if obrigatorio and not t:
        raise Invalido(f"Informe {rotulo}.")
    if len(t) > tam:
        raise Invalido(f"{rotulo[0].upper() + rotulo[1:]}: até {tam} caracteres.")
    return t or None


def inteiro(txt, rotulo: str, minimo: int, maximo: int = 100_000) -> int:
    try:
        n = int(str(txt).strip())
    except (TypeError, ValueError):
        raise Invalido(f"{rotulo}: informe um número inteiro.")
    if not minimo <= n <= maximo:
        raise Invalido(f"{rotulo}: use um valor entre {minimo} e {maximo}.")
    return n


def cnpj_valido(txt: str) -> Optional[str]:
    d = re.sub(r"\D", "", txt or "")
    if not d:
        return None
    if len(d) != 14 or d == d[0] * 14:
        raise Invalido("CNPJ do fornecedor inválido (14 dígitos).")
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(a) * b for a, b in zip(d[:n], pesos)) % 11
        if int(d[n]) != (0 if resto < 2 else 11 - resto):
            raise Invalido("CNPJ do fornecedor inválido (dígito verificador não confere).")
    return d


def fmt_cnpj(d: Optional[str]) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if d and len(d) == 14 else (d or "")


def seriais(txt: str) -> list[str]:
    """Nºs de série separados por vírgula, ponto e vírgula ou quebra de linha."""
    lista = [s.strip().upper() for s in re.split(r"[,;\n]", txt or "") if s.strip()]
    if any(len(s) > 100 for s in lista):
        raise Invalido("Nº de série: até 100 caracteres cada.")
    repetidos = sorted({s for s in lista if lista.count(s) > 1})
    if repetidos:
        raise Invalido("Nº de série repetido: " + ", ".join(repetidos) + ".")
    return lista


def ler_pdf(arquivo: Optional[UploadFile]) -> Optional[tuple[bytes, str]]:
    """Conteúdo e nome do PDF enviado (None se nenhum arquivo foi escolhido)."""
    if arquivo is None or not arquivo.filename:
        return None
    dados = arquivo.file.read(MAX_PDF + 1)
    if not dados:
        return None
    if len(dados) > MAX_PDF:
        raise Invalido("O PDF da nota fiscal passa de 10 MB.")
    if not dados.startswith(b"%PDF"):
        raise Invalido("O anexo da nota fiscal precisa ser um arquivo PDF.")
    return dados, arquivo.filename[-200:]


def nota_fiscal(db: Session, user: User, v: dict, pdf, obrigatoria: bool) -> Optional[NotaFiscal]:
    """Monta a nota fiscal a partir do formulário (campos nf_*). Sem número e não obrigatória: None."""
    numero = texto(v.get("nf_numero"), 20, "o número da nota fiscal", obrigatoria)
    if not numero:
        if pdf or any((v.get(c) or "").strip() for c in ("nf_serie", "nf_chave", "nf_cnpj", "nf_protocolo")):
            raise Invalido("Informe o número da nota fiscal (ou deixe todos os campos da nota em branco).")
        return None
    cnpj = cnpj_valido(v.get("nf_cnpj"))
    if obrigatoria and not cnpj:
        raise Invalido("Informe o CNPJ do fornecedor.")
    chave = re.sub(r"\D", "", v.get("nf_chave") or "") or None
    if chave and len(chave) != 44:
        raise Invalido("A chave de acesso da NF-e tem 44 dígitos.")
    if chave and db.scalar(select(NotaFiscal.id).where(NotaFiscal.chave_acesso == chave)):
        raise Invalido("Essa nota fiscal (chave de acesso) já foi registrada.")
    emissao = None
    if (v.get("nf_emissao") or "").strip():
        try:
            emissao = date.fromisoformat(v["nf_emissao"].strip())
        except ValueError:
            raise Invalido("Data de emissão inválida.")
        if emissao > date.today():
            raise Invalido("A data de emissão não pode ser no futuro.")
    return NotaFiscal(numero=numero, serie=texto(v.get("nf_serie"), 5, "a série da nota"), data_emissao=emissao,
                      cnpj_fornecedor=cnpj, chave_acesso=chave,
                      protocolo=texto(v.get("nf_protocolo"), 50, "o protocolo"), usuario_id=user.id)


def gravar_pdf(nf: NotaFiscal, pdf) -> Optional[str]:
    """Salva o PDF em data/notasfiscais/ e devolve o caminho (para apagar se a gravação no banco falhar)."""
    if not pdf:
        return None
    PASTA_NF.mkdir(parents=True, exist_ok=True)
    nome = f"NF_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.pdf"
    (PASTA_NF / nome).write_bytes(pdf[0])
    nf.arquivo, nf.arquivo_nome = nome, pdf[1]
    return nome


def apagar_pdf(nome: Optional[str]) -> None:
    if nome:
        (PASTA_NF / nome).unlink(missing_ok=True)


def mover_saldo(db: Session, peca_id: int, delta: int) -> int:
    """Soma delta ao saldo de forma atômica; numa saída sem saldo suficiente, não altera nada."""
    cond = [Peca.id == peca_id] + ([Peca.quantidade >= -delta] if delta < 0 else [])
    r = db.execute(update(Peca).where(*cond).values(quantidade=Peca.quantidade + delta, atualizado_em=agora()))
    if r.rowcount != 1:
        disp = db.scalar(select(Peca.quantidade).where(Peca.id == peca_id))
        raise Invalido(f"Saldo insuficiente: há {disp} em estoque.")
    return db.scalar(select(Peca.quantidade).where(Peca.id == peca_id))


# ---------- consultas ----------
def _peca(db: Session, id_: int) -> Peca:
    p = db.get(Peca, id_)
    if not p:
        raise HTTPException(404, "Peça não encontrada")
    return p


def _categorias(db: Session) -> list[CategoriaPeca]:
    return db.scalars(select(CategoriaPeca).order_by(CategoriaPeca.nome)).all()


def _filtro_situacao(s: str):
    return {"esgotado": Peca.quantidade <= 0,
            "baixo": (Peca.quantidade > 0) & (Peca.quantidade <= Peca.quantidade_minima),
            "ok": Peca.quantidade > Peca.quantidade_minima}.get(s)


def _mov_view(m: PecaMovimento) -> PecaMovimento:
    m.quando = hora_local(m.criado_em)
    return m


@router.get("/almoxarifado")
def almoxarifado(request: Request, q: str = "", situacao: str = "", cat: int = 0, pagina_n: int = 1,
                 ok: str = "", erro: str = "", db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    filtros = []
    if q.strip():
        like = f"%{q.strip()[:100]}%"
        filtros.append(or_(Peca.descricao.ilike(like), Peca.marca.ilike(like), Peca.modelo.ilike(like)))
    if _filtro_situacao(situacao) is not None:
        filtros.append(_filtro_situacao(situacao))
    if cat:
        filtros.append(Peca.categoria_id == cat)
    total = db.scalar(select(func.count(Peca.id)).where(*filtros))
    paginas = max(1, math.ceil(total / POR_PAGINA))
    pagina_n = min(max(1, pagina_n), paginas)
    pecas = db.scalars(select(Peca).join(CategoriaPeca).where(*filtros).options(selectinload(Peca.categoria))
                       .order_by(CategoriaPeca.nome, Peca.descricao, Peca.id)
                       .offset((pagina_n - 1) * POR_PAGINA).limit(POR_PAGINA)).all()
    # últimas 5 movimentações de cada peça da página (mostradas ao expandir a linha)
    ultimos: dict[int, list] = {p.id: [] for p in pecas}
    if pecas:
        rn = func.row_number().over(partition_by=PecaMovimento.peca_id,
                                    order_by=(PecaMovimento.criado_em.desc(), PecaMovimento.id.desc())).label("rn")
        sub = select(PecaMovimento.id, rn).where(PecaMovimento.peca_id.in_(ultimos)).subquery()
        movs = db.scalars(select(PecaMovimento).join(sub, sub.c.id == PecaMovimento.id).where(sub.c.rn <= 5)
                          .options(selectinload(PecaMovimento.usuario))
                          .order_by(PecaMovimento.criado_em.desc(), PecaMovimento.id.desc())).all()
        for m in movs:
            ultimos[m.peca_id].append(_mov_view(m))
    resumo = {s: db.scalar(select(func.count(Peca.id)).where(_filtro_situacao(s))) for s in SITUACOES}
    return pagina(request, "almoxarifado.html", user, pecas=pecas, ultimos=ultimos, total=total, resumo=resumo,
                  q=q, situacao=situacao if situacao in SITUACOES else "", cat=cat, pagina_n=pagina_n, paginas=paginas,
                  categorias=_categorias(db), ok=AVISOS.get(ok), erro=ERROS.get(erro))


# ---------- categorias ----------
@router.post("/almoxarifado/categorias")
def categoria_criar(nome: str = Form(""), icone: str = Form(""), db: Session = Depends(get_db),
                    user: User = Depends(gestor_web)):
    nome = " ".join(nome.split()).upper()
    if not nome or len(nome) > 50:
        return RedirectResponse("/almoxarifado?erro=cat_nome", 303)
    if db.scalar(select(CategoriaPeca.id).where(func.upper(CategoriaPeca.nome) == nome)):
        return RedirectResponse("/almoxarifado?erro=cat_existe", 303)
    db.add(CategoriaPeca(nome=nome, icone=(icone.strip() or "📦")[:16]))
    db.commit()
    return RedirectResponse("/almoxarifado?ok=categoria", 303)


@router.post("/almoxarifado/categorias/{id_}/excluir")
def categoria_excluir(id_: int, db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    c = db.get(CategoriaPeca, id_)
    if not c:
        raise HTTPException(404, "Categoria não encontrada")
    if db.scalar(select(Peca.id).where(Peca.categoria_id == id_).limit(1)):
        return RedirectResponse("/almoxarifado?erro=cat_em_uso", 303)
    db.delete(c)
    db.commit()
    return RedirectResponse("/almoxarifado?ok=cat_excluida", 303)


# ---------- catálogo (SKU) ----------
def _form_peca(request, db, user, v, peca=None, erro=None, status=200):
    return pagina(request, "peca_form.html", user, status, v=v, peca=peca, erro=erro, categorias=_categorias(db))


def _dados_peca(db: Session, v: dict) -> dict:
    cat = db.get(CategoriaPeca, int(v["categoria_id"])) if str(v.get("categoria_id") or "").isdigit() else None
    if not cat:
        raise Invalido("Escolha a categoria.")
    return dict(categoria_id=cat.id, descricao=maiusc(v["descricao"], 200, "a descrição", True),
                marca=maiusc(v["marca"], 100, "a marca"), modelo=maiusc(v["modelo"], 100, "o modelo"),
                quantidade_minima=inteiro(v["quantidade_minima"], "Estoque mínimo", 0),
                observacoes=texto(v["observacoes"], 500, "as observações"))


def _duplicada(db: Session, d: dict, ignorar: int = 0) -> bool:
    return bool(db.scalar(select(Peca.id).where(
        Peca.id != ignorar, Peca.categoria_id == d["categoria_id"], Peca.descricao == d["descricao"],
        func.coalesce(Peca.marca, "") == (d["marca"] or ""), func.coalesce(Peca.modelo, "") == (d["modelo"] or ""))))


CAMPOS_PECA = ("categoria_id", "descricao", "marca", "modelo", "quantidade_minima", "observacoes")


@router.get("/almoxarifado/pecas/nova")
def peca_nova(request: Request, cat: str = "", db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    v = {c: "" for c in CAMPOS_PECA} | {"quantidade_minima": "2", "categoria_id": cat}
    return _form_peca(request, db, user, v)


@router.post("/almoxarifado/pecas/nova")
def peca_criar(request: Request, categoria_id: str = Form(""), descricao: str = Form(""), marca: str = Form(""),
               modelo: str = Form(""), quantidade_minima: str = Form("2"), observacoes: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    v = dict(categoria_id=categoria_id, descricao=descricao, marca=marca, modelo=modelo,
             quantidade_minima=quantidade_minima, observacoes=observacoes)
    try:
        d = _dados_peca(db, v)
        if _duplicada(db, d):
            raise Invalido("Essa peça já está no catálogo (mesma categoria, descrição, marca e modelo).")
    except Invalido as e:
        return _form_peca(request, db, user, v, erro=str(e), status=422)
    p = Peca(**d, quantidade=0)  # toda peça nasce com saldo zero; o saldo só muda por entrada/saída
    db.add(p)
    db.commit()
    return RedirectResponse(f"/almoxarifado/pecas/{p.id}?ok=peca", 303)


@router.get("/almoxarifado/pecas/{id_}/editar")
def peca_editar(id_: int, request: Request, db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    p = _peca(db, id_)
    v = {c: ("" if getattr(p, c) is None else str(getattr(p, c))) for c in CAMPOS_PECA}
    return _form_peca(request, db, user, v, peca=p)


@router.post("/almoxarifado/pecas/{id_}/editar")
def peca_salvar(id_: int, request: Request, categoria_id: str = Form(""), descricao: str = Form(""),
                marca: str = Form(""), modelo: str = Form(""), quantidade_minima: str = Form("2"),
                observacoes: str = Form(""), db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    p = _peca(db, id_)
    v = dict(categoria_id=categoria_id, descricao=descricao, marca=marca, modelo=modelo,
             quantidade_minima=quantidade_minima, observacoes=observacoes)
    try:
        d = _dados_peca(db, v)
        if _duplicada(db, d, ignorar=p.id):
            raise Invalido("Já existe outra peça igual no catálogo (mesma categoria, descrição, marca e modelo).")
    except Invalido as e:
        return _form_peca(request, db, user, v, peca=p, erro=str(e), status=422)
    for k, val in d.items():
        setattr(p, k, val)
    db.commit()
    return RedirectResponse(f"/almoxarifado/pecas/{p.id}?ok=editada", 303)


@router.post("/almoxarifado/pecas/{id_}/excluir")
def peca_excluir(id_: int, db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    db.delete(_peca(db, id_))  # o extrato da peça vai junto
    db.commit()
    return RedirectResponse("/almoxarifado?ok=excluida", 303)


# ---------- extrato e movimentação avulsa ----------
CAMPOS_MOV = ("tipo", "quantidade", "marca", "modelo", "numero_serie", "chamado", "patrimonio", "observacoes",
              "nf_numero", "nf_serie", "nf_emissao", "nf_cnpj", "nf_chave", "nf_protocolo")


def _ver_peca(request, db, user, p, v=None, erro=None, ok=None, pg=1, status=200):
    total = db.scalar(select(func.count(PecaMovimento.id)).where(PecaMovimento.peca_id == p.id))
    paginas = max(1, math.ceil(total / POR_PAGINA_EXTRATO))
    pg = min(max(1, pg), paginas)
    movs = db.scalars(select(PecaMovimento).where(PecaMovimento.peca_id == p.id)
                      .options(selectinload(PecaMovimento.usuario), selectinload(PecaMovimento.nota_fiscal),
                               selectinload(PecaMovimento.equipamento))
                      .order_by(PecaMovimento.criado_em.desc(), PecaMovimento.id.desc())
                      .offset((pg - 1) * POR_PAGINA_EXTRATO).limit(POR_PAGINA_EXTRATO)).all()
    v = v or ({c: "" for c in CAMPOS_MOV} | {"tipo": "entrada", "quantidade": "1"})
    return pagina(request, "peca_ver.html", user, status, pc=p, movs=[_mov_view(m) for m in movs], total=total,
                  pg=pg, paginas=paginas, v=v, erro=erro, ok=ok, fmt_cnpj=fmt_cnpj)


@router.get("/almoxarifado/pecas/{id_}")
def peca_ver(id_: int, request: Request, tipo: str = "entrada", pg: int = 1, ok: str = "",
             db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    v = {c: "" for c in CAMPOS_MOV} | {"tipo": "saida" if tipo == "saida" else "entrada", "quantidade": "1"}
    return _ver_peca(request, db, user, _peca(db, id_), v=v, ok=AVISOS.get(ok), pg=pg)


@router.post("/almoxarifado/pecas/{id_}/movimentar")
def peca_movimentar(id_: int, request: Request, tipo: str = Form("entrada"), quantidade: str = Form("1"),
                    marca: str = Form(""), modelo: str = Form(""), numero_serie: str = Form(""),
                    chamado: str = Form(""), patrimonio: str = Form(""), observacoes: str = Form(""),
                    nf_numero: str = Form(""), nf_serie: str = Form(""), nf_emissao: str = Form(""),
                    nf_cnpj: str = Form(""), nf_chave: str = Form(""), nf_protocolo: str = Form(""),
                    nf_pdf: Optional[UploadFile] = File(None),
                    db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    p = _peca(db, id_)
    v = dict(tipo=tipo, quantidade=quantidade, marca=marca, modelo=modelo, numero_serie=numero_serie,
             chamado=chamado, patrimonio=patrimonio, observacoes=observacoes, nf_numero=nf_numero, nf_serie=nf_serie,
             nf_emissao=nf_emissao, nf_cnpj=nf_cnpj, nf_chave=nf_chave, nf_protocolo=nf_protocolo)
    arquivo = None
    try:
        if tipo not in ("entrada", "saida"):
            raise Invalido("Tipo de movimentação inválido.")
        qtd = inteiro(quantidade, "Quantidade", 1)
        m = PecaMovimento(peca_id=p.id, tipo=tipo, quantidade=qtd, usuario_id=user.id,
                          observacoes=texto(observacoes, 500, "as observações"))
        if tipo == "entrada":
            m.marca, m.modelo = maiusc(marca, 100, "a marca"), maiusc(modelo, 100, "o modelo")
            m.numero_serie = maiusc(numero_serie, 100, "o nº de série")
            pdf = ler_pdf(nf_pdf)
            nf = nota_fiscal(db, user, v, pdf, obrigatoria=False)
            if nf:
                db.add(nf)
                arquivo = gravar_pdf(nf, pdf)
                m.nota_fiscal = nf
            m.saldo_apos = mover_saldo(db, p.id, qtd)
        else:
            m.chamado = texto(chamado, 100, "o nº do chamado", True)
            m.patrimonio = texto(patrimonio, 100, "o patrimônio do equipamento que recebe a peça", True)
            eq = equipamento_por_patrimonio(db, m.patrimonio)
            m.equipamento_id = eq.id if eq else None
            m.saldo_apos = mover_saldo(db, p.id, -qtd)
        db.add(m)
        db.commit()
    except Invalido as e:
        db.rollback()
        apagar_pdf(arquivo)
        return _ver_peca(request, db, user, p, v=v, erro=str(e), status=422)
    except Exception:
        db.rollback()
        apagar_pdf(arquivo)
        raise
    return RedirectResponse(f"/almoxarifado/pecas/{p.id}?ok={tipo}", 303)


# ---------- entrada em lote com nota fiscal ----------
CAMPOS_NF = ("nf_numero", "nf_serie", "nf_emissao", "nf_cnpj", "nf_chave", "nf_protocolo")


def _form_lote(request, db, user, v, itens, erro=None, status=200):
    pecas = db.scalars(select(Peca).join(CategoriaPeca).options(selectinload(Peca.categoria))
                       .order_by(CategoriaPeca.nome, Peca.descricao)).all()
    return pagina(request, "almox_lote.html", user, status, v=v, itens=itens, pecas=pecas, erro=erro)


@router.get("/almoxarifado/lote")
def lote(request: Request, db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    itens = [{"peca_id": "", "quantidade": "", "seriais": ""} for _ in range(3)]
    return _form_lote(request, db, user, {c: "" for c in CAMPOS_NF + ("observacoes",)}, itens)


@router.post("/almoxarifado/lote")
async def lote_salvar(request: Request, db: Session = Depends(get_db), user: User = Depends(gestor_web)):
    form = await request.form()
    v = {c: str(form.get(c) or "") for c in CAMPOS_NF + ("observacoes",)}
    linhas = list(zip(form.getlist("peca_id"), form.getlist("quantidade"), form.getlist("seriais")))
    itens = [{"peca_id": str(a), "quantidade": str(b), "seriais": str(c)} for a, b, c in linhas][:100]
    arquivo = None
    try:
        enviado = form.get("nf_pdf")
        pdf = ler_pdf(enviado if hasattr(enviado, "file") else None)
        nf = nota_fiscal(db, user, v, pdf, obrigatoria=True)
        obs = texto(v["observacoes"], 500, "as observações")
        cesta = []
        for n, it in enumerate(itens, 1):
            if not it["peca_id"] and not it["quantidade"].strip() and not it["seriais"].strip():
                continue  # linha em branco
            peca = db.get(Peca, int(it["peca_id"])) if it["peca_id"].isdigit() else None
            if not peca:
                raise Invalido(f"Item {n}: escolha a peça.")
            ss = seriais(it["seriais"])
            qtd = inteiro(it["quantidade"], f"Item {n} (quantidade)", 1) if it["quantidade"].strip() else len(ss)
            if qtd < 1:
                raise Invalido(f"Item {n}: informe a quantidade.")
            if len(ss) > qtd:
                raise Invalido(f"Item {n}: {len(ss)} nºs de série para quantidade {qtd}.")
            cesta.append((peca, qtd, ss))
        if not cesta:
            raise Invalido("Inclua pelo menos uma peça na cesta.")
        db.add(nf)
        arquivo = gravar_pdf(nf, pdf)
        for peca, qtd, ss in cesta:
            # com nº de série: um movimento por unidade; o que sobrar entra num movimento sem série
            partes = [(1, s) for s in ss] + ([(qtd - len(ss), None)] if qtd > len(ss) else [])
            for q, serie in partes:
                db.add(PecaMovimento(peca_id=peca.id, tipo="entrada", quantidade=q, numero_serie=serie,
                                     marca=peca.marca, modelo=peca.modelo, usuario_id=user.id, observacoes=obs,
                                     nota_fiscal=nf, saldo_apos=mover_saldo(db, peca.id, q)))
        db.commit()
    except Invalido as e:
        db.rollback()
        apagar_pdf(arquivo)
        return _form_lote(request, db, user, v, itens or [{"peca_id": "", "quantidade": "", "seriais": ""}],
                          erro=str(e), status=422)
    except Exception:
        db.rollback()
        apagar_pdf(arquivo)
        raise
    return RedirectResponse("/almoxarifado?ok=lote", 303)


# ---------- PDF da nota fiscal ----------
@router.get("/almoxarifado/notas/{id_}/pdf")
def nota_pdf(id_: int, db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    nf = db.get(NotaFiscal, id_)
    if not nf or not nf.arquivo or not (PASTA_NF / nf.arquivo).is_file():
        raise HTTPException(404, "PDF não encontrado")
    nome = re.sub(r"[^\w.-]", "_", nf.arquivo_nome or f"NF_{nf.numero}.pdf")
    return FileResponse(PASTA_NF / nf.arquivo, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{nome}"'})
