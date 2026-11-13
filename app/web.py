"""Telas HTML (renderizadas no servidor, sem JavaScript de aplicação)."""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_, select, true, update
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .database import get_db
from .models import Equipamento, Etiqueta, Guia, User
from .routers.etiquetas import gerar_etiqueta, qr_data_uri, texto_qr
from .routers.guias import criar as criar_guia
from .schemas import MOTIVOS, EtiquetaCreate, GuiaCreate, UserCreate
from .security import (bloqueado, confere_senha, criar_token, hash_senha, limpar_falhas, registrar_falha,
                       usuario_por_token)

COOKIE = "sessao"
FUSO = ZoneInfo("America/Bahia")
SD = "CTI - SERVICE DESK"
TIPOS = ["Computador", "Monitor", "Teclado", "Mouse", "Switch", "Estabilizador", "Notebook", "Projetor", "Webcam"]
COLS_ITEM = ("tipo_equipamento", "modelo", "patrimonio", "serial", "hostname", "ip")
LINHAS = 3  # linhas iniciais do formulário de guia (o botão + cria mais)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")  # autoescape ligado
STATIC = Path(__file__).parent / "static"


def static_url(nome: str) -> str:
    """URL do arquivo estático com ?v=<data de modificação>: o navegador baixa de novo quando o arquivo muda."""
    try:
        return f"/static/{nome}?v={int((STATIC / nome).stat().st_mtime)}"
    except OSError:
        return f"/static/{nome}"


templates.env.globals["static_url"] = static_url
router = APIRouter(include_in_schema=False)


def pagina(request: Request, nome: str, user=None, status: int = 200, **kw):
    return templates.TemplateResponse(request, nome, {"user": user, **kw}, status_code=status)


def usuario_web(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    user = usuario_por_token(token, db) if token else None
    if not user:
        raise HTTPException(303, headers={"Location": "/login"})
    return user


def admin_web(user: User = Depends(usuario_web)) -> User:
    if user.papel != "admin":
        raise HTTPException(403, "Apenas administradores")
    return user


def hora_local(dt, fmt="%d/%m/%Y %H:%M"):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(FUSO).strftime(fmt)


# ---------- sessão ----------
@router.get("/login")
def login_form(request: Request):
    return pagina(request, "login.html")


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), db: Session = Depends(get_db)):
    chave = f"{request.client.host if request.client else '?'}|{username.lower()}"
    if bloqueado(chave):
        return pagina(request, "login.html", status=429, erro="Muitas tentativas. Aguarde 15 minutos.")
    user = db.scalar(select(User).where(User.username == username))
    ok = confere_senha(password, user.senha_hash) if user else confere_senha(password, "x")
    if not (user and ok and user.ativo):
        registrar_falha(chave)
        return pagina(request, "login.html", status=401, erro="Usuário ou senha incorretos.")
    limpar_falhas(chave)
    resp = RedirectResponse("/", 303)
    resp.set_cookie(COOKIE, criar_token(user.id), httponly=True, samesite="strict",
                    secure=settings.cookie_seguro, max_age=settings.access_token_minutes * 60)
    return resp


@router.post("/sair")
def sair():
    resp = RedirectResponse("/login", 303)
    resp.delete_cookie(COOKIE)
    return resp


@router.get("/")
def painel(request: Request, user: User = Depends(usuario_web)):
    return pagina(request, "painel.html", user)


# ---------- etiquetas ----------
def _etiquetas(request, db, user, status=200, erro=None, v=None):
    recentes = db.scalars(select(Etiqueta).options(selectinload(Etiqueta.equipamento))
                          .where(Etiqueta.operador_id == user.id, Etiqueta.oculta.is_(False)).order_by(Etiqueta.id.desc()).limit(12)).all()
    itens = [{"id": e.id, "eq": e.foto, "qr": qr_data_uri(texto_qr(e.foto))} for e in recentes]
    campos = ("hostname", "ip", "patrimonio", "serial", "localidade", "mascara", "gateway")
    return pagina(request, "etiquetas.html", user, status, etiquetas=itens, erro=erro,
                  v=v or {c: "" for c in campos})


@router.get("/etiquetas")
def etiquetas(request: Request, db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    return _etiquetas(request, db, user)


@router.post("/etiquetas")
def etiqueta_criar(request: Request, hostname: str = Form(""), ip: str = Form(""), patrimonio: str = Form(""),
                   serial: str = Form(""), localidade: str = Form(""), mascara: str = Form(""),
                   gateway: str = Form(""), db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    v = dict(hostname=hostname, ip=ip, patrimonio=patrimonio, serial=serial,
             localidade=localidade, mascara=mascara, gateway=gateway)
    try:
        dados = EtiquetaCreate(**v)
    except ValidationError as e:
        campos = sorted({str(x["loc"][0]) for x in e.errors()})
        return _etiquetas(request, db, user, 422, "Verifique os campos: " + ", ".join(campos), v)
    gerar_etiqueta(db, dados, user)
    return RedirectResponse("/etiquetas", 303)


@router.post("/etiquetas/limpar")
def etiquetas_limpar(db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    """Oculta todas as etiquetas recentes do operador (o histórico continua no banco)."""
    db.execute(update(Etiqueta).where(Etiqueta.operador_id == user.id, Etiqueta.oculta.is_(False))
               .values(oculta=True))
    db.commit()
    return RedirectResponse("/etiquetas", 303)


@router.post("/etiquetas/{id_}/ocultar")
def etiqueta_ocultar(id_: int, db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    """Oculta uma etiqueta da lista de recentes (só o próprio operador pode)."""
    et = db.get(Etiqueta, id_)
    if not et or et.operador_id != user.id:
        raise HTTPException(404, "Etiqueta não encontrada")
    et.oculta = True
    db.commit()
    return RedirectResponse("/etiquetas", 303)


# ---------- guias ----------
def _form_guia(request, user, v=None, linhas=None, erro=None, status=200):
    v = v or {"tipo": SAIDA, "motivo": "", "chamado": "", "remetente": "", "destinatario": "", "responsavel": ""}
    linhas = linhas or [{c: "" for c in COLS_ITEM} | {"tipo_equipamento": "Computador"} for _ in range(LINHAS)]
    return pagina(request, "guias_nova.html", user, status, v=v, linhas=linhas, tipos=TIPOS, erro=erro,
                  tipos_guia=[SAIDA, ENTRADA], motivos=MOTIVOS)


@router.get("/guias/nova")
def guia_nova(request: Request, user: User = Depends(usuario_web)):
    return _form_guia(request, user)


@router.post("/guias/nova")
async def guia_criar(request: Request, db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    f = await request.form()
    v = {c: str(f.get(c, "")).strip() for c in ("tipo", "motivo", "chamado", "remetente", "destinatario", "responsavel")}
    linhas = [dict(zip(COLS_ITEM, (str(x).strip() for x in vals)))
              for vals in zip(*(f.getlist(c) for c in COLS_ITEM))]
    itens = [l for l in linhas if any(l[c] for c in COLS_ITEM[1:])]
    if v["tipo"].startswith("GUIA DE ENTRADA"):
        v["destinatario"] = v["destinatario"] or SD
    elif v["tipo"].startswith("GUIA DE SAÍDA"):
        v["remetente"] = v["remetente"] or SD
    if not v["chamado"]:
        return _form_guia(request, user, v, linhas, "Informe o número do chamado.", 422)
    if v["motivo"] and v["motivo"] not in MOTIVOS:
        return _form_guia(request, user, v, linhas, "Motivo inválido.", 422)
    # tipo gravado = tipo + motivo (ex.: "GUIA DE SAÍDA - MANUTENÇÃO")
    campos = {k: val for k, val in v.items() if k != "motivo"}
    campos["tipo"] = f"{v['tipo']} - {v['motivo']}" if v["motivo"] else v["tipo"]
    try:
        dados = GuiaCreate(**campos, itens=itens)
    except ValidationError:
        return _form_guia(request, user, v, linhas, "Verifique os campos e informe ao menos um equipamento (IP válido, se preenchido).", 422)
    guia = criar_guia(dados, db, user)
    return RedirectResponse(f"/guias/{guia.id}", 303)


SAIDA, ENTRADA = "GUIA DE SAÍDA", "GUIA DE ENTRADA"
E_SAIDA = Guia.tipo.like(SAIDA + "%")  # saída comum ou desfazimento
PRONTA = or_(Guia.status.is_(None), Guia.status == "pronta")
FILTROS = {  # aba -> (rótulo, condição)
    "todas": ("Todas", None),
    "prontas": ("Prontas p/ entrega", E_SAIDA & PRONTA),
    "entregues": ("Entregues", E_SAIDA & (Guia.status == "entregue")),
    "entrada": ("Entrada", Guia.tipo.like(ENTRADA + "%")),
}
AVISOS_GUIA = {"entregue": "Entrega registrada.", "reaberta": "Guia voltou para “pronta”."}
ERROS_GUIA = {"entrega": "Informe quem entregou e quem retirou (até 200 caracteres cada)."}


@router.get("/guias")
def guias(request: Request, f: str = "todas", ok: str = "", erro: str = "",
          db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    f = f if f in FILTROS else "todas"
    stmt = select(Guia).options(selectinload(Guia.itens)).order_by(Guia.criado_em.desc(), Guia.id.desc()).limit(500)
    if FILTROS[f][1] is not None:
        stmt = stmt.where(FILTROS[f][1])
    lista = db.scalars(stmt).all()
    for g in lista:
        g.data = hora_local(g.criado_em)
        g.entregue_txt = hora_local(g.entregue_em) if g.entregue_em else ""
    contagem = {k: db.scalar(select(func.count(Guia.id)).where(c if c is not None else true())) for k, (_, c) in FILTROS.items()}
    abas = [(k, rotulo, contagem[k]) for k, (rotulo, _) in FILTROS.items()]
    return pagina(request, "guias_lista.html", user, guias=lista, f=f, abas=abas,
                  ok=AVISOS_GUIA.get(ok), erro=ERROS_GUIA.get(erro))


def _guia_saida(db: Session, id_: int) -> Guia:
    g = db.get(Guia, id_)
    if not g or not g.tipo.startswith(SAIDA):
        raise HTTPException(404, "Guia de saída não encontrada")
    return g


def _voltar(id_: int, origem: str, f: str, **qs) -> RedirectResponse:
    """Volta para a tela de origem (só destinos internos fixos)."""
    if origem == "guia":
        url = f"/guias/{id_}"
    else:
        url = "/guias"
        if f in FILTROS and f != "todas":
            qs = {"f": f, **qs}
    if qs:
        url += "?" + "&".join(f"{k}={v}" for k, v in qs.items())
    return RedirectResponse(url, 303)


@router.post("/guias/{id_}/entregar")
def guia_entregar(id_: int, entregue_por: str = Form(""), retirado_por: str = Form(""),
                  origem: str = Form(""), f: str = Form(""),
                  db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    g = _guia_saida(db, id_)
    entregue_por, retirado_por = entregue_por.strip(), retirado_por.strip()
    if not (0 < len(entregue_por) <= 200 and 0 < len(retirado_por) <= 200):
        return _voltar(id_, origem, f, erro="entrega")
    g.status, g.entregue_por, g.retirado_por = "entregue", entregue_por, retirado_por
    g.entregue_em, g.entrega_operador_id = datetime.now(timezone.utc), user.id
    db.commit()
    return _voltar(id_, origem, f, ok="entregue")


@router.post("/guias/{id_}/reabrir")
def guia_reabrir(id_: int, origem: str = Form(""), f: str = Form(""),
                 db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    g = _guia_saida(db, id_)
    g.status, g.entregue_por, g.retirado_por, g.entregue_em, g.entrega_operador_id = "pronta", None, None, None, None
    db.commit()
    return _voltar(id_, origem, f, ok="reaberta")


@router.get("/guias/{id_}")
def guia_ver(id_: int, request: Request, data: int = 1, ok: str = "", erro: str = "",
             db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    g = db.get(Guia, id_)
    if not g:
        raise HTTPException(404, "Guia não encontrada")
    usar = bool(data)
    txt = f"DATA: {hora_local(g.criado_em, '%d/%m/%Y às %H:%M')}" if usar else "DATA: _______/_______/_____________"
    entregue_txt = hora_local(g.entregue_em, "%d/%m/%Y às %H:%M") if g.entregue_em else ""
    return pagina(request, "guia_ver.html", user, g=g, usar_data=usar, data_txt=txt, entregue_txt=entregue_txt,
                  ok=AVISOS_GUIA.get(ok), erro=ERROS_GUIA.get(erro))


# ---------- usuários (somente admin) ----------
PAPEIS = ["operador", "admin"]
AVISOS = {"criado": "Usuário criado.", "papel": "Papel atualizado.", "senha": "Senha redefinida.",
          "ativado": "Usuário ativado.", "desativado": "Usuário desativado."}
ERROS = {"proprio": "Você não pode alterar o próprio papel nem se desativar.",
         "papel": "Papel inválido.",
         "senha": "Senha inválida: use de 8 a 72 caracteres, sem espaço no início ou no fim."}


def _usuarios(request, db, user, v=None, erro=None, ok=None, status=200):
    lista = db.scalars(select(User).order_by(User.nome, User.username)).all()
    v = v or {"username": "", "nome": "", "papel": "operador"}
    return pagina(request, "usuarios.html", user, status, usuarios=lista, papeis=PAPEIS, v=v, erro=erro, ok=ok)


def _senha_ok(senha: str) -> bool:
    # bcrypt só aceita até 72 bytes; espaços nas pontas fariam a senha divergir no login
    return len(senha) >= 8 and len(senha.encode()) <= 72 and senha == senha.strip()


def _alvo(db: Session, id_: int) -> User:
    alvo = db.get(User, id_)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    return alvo


@router.get("/usuarios")
def usuarios(request: Request, ok: str = "", erro: str = "", db: Session = Depends(get_db),
             user: User = Depends(admin_web)):
    return _usuarios(request, db, user, erro=ERROS.get(erro), ok=AVISOS.get(ok))


@router.post("/usuarios")
def usuario_criar(request: Request, username: str = Form(""), nome: str = Form(""), senha: str = Form(""),
                  papel: str = Form("operador"), db: Session = Depends(get_db), user: User = Depends(admin_web)):
    v = dict(username=username.strip(), nome=nome.strip(), papel=papel)
    if not _senha_ok(senha):
        return _usuarios(request, db, user, v, ERROS["senha"], status=422)
    try:
        dados = UserCreate(**v, senha=senha)
    except ValidationError as e:
        campos = sorted({str(x["loc"][0]) for x in e.errors()})
        return _usuarios(request, db, user, v, "Verifique os campos: " + ", ".join(campos)
                         + " (login: 3 a 50 letras, números, . _ -).", status=422)
    if db.scalar(select(User.id).where(func.lower(User.username) == dados.username.lower())):
        return _usuarios(request, db, user, v, "Já existe um usuário com esse login.", status=409)
    db.add(User(username=dados.username, nome=dados.nome, senha_hash=hash_senha(dados.senha), papel=dados.papel))
    db.commit()
    return RedirectResponse("/usuarios?ok=criado", 303)


@router.post("/usuarios/{id_}/papel")
def usuario_papel(id_: int, papel: str = Form(""), db: Session = Depends(get_db), user: User = Depends(admin_web)):
    alvo = _alvo(db, id_)
    if alvo.id == user.id:
        return RedirectResponse("/usuarios?erro=proprio", 303)
    if papel not in PAPEIS:
        return RedirectResponse("/usuarios?erro=papel", 303)
    alvo.papel = papel
    db.commit()
    return RedirectResponse("/usuarios?ok=papel", 303)


@router.post("/usuarios/{id_}/ativo")
def usuario_ativo(id_: int, db: Session = Depends(get_db), user: User = Depends(admin_web)):
    alvo = _alvo(db, id_)
    if alvo.id == user.id:
        return RedirectResponse("/usuarios?erro=proprio", 303)
    alvo.ativo = not alvo.ativo
    db.commit()
    return RedirectResponse("/usuarios?ok=" + ("ativado" if alvo.ativo else "desativado"), 303)


@router.post("/usuarios/{id_}/senha")
def usuario_senha(id_: int, senha: str = Form(""), db: Session = Depends(get_db), user: User = Depends(admin_web)):
    alvo = _alvo(db, id_)
    if not _senha_ok(senha):
        return RedirectResponse("/usuarios?erro=senha", 303)
    alvo.senha_hash = hash_senha(senha)
    db.commit()
    return RedirectResponse("/usuarios?ok=senha", 303)


# ---------- relatórios ----------
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
TIPOS_REL = [("todos", "Guias e etiquetas"), ("guias", "Guias"), ("etiquetas", "Etiquetas")]


def _local(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(FUSO)


def _parse_mes(txt, hoje):
    """Aceita 'AAAA-MM'; qualquer outro valor cai no mês atual."""
    try:
        a, m = (int(x) for x in txt.split("-"))
        if 2000 <= a <= 2100 and 1 <= m <= 12:
            return a, m
    except ValueError:
        pass
    return hoje.year, hoje.month


@router.get("/relatorios")
def relatorios(request: Request, mes: str = "", tipo: str = "todos", db: Session = Depends(get_db),
               user: User = Depends(usuario_web)):
    ano, m = _parse_mes(mes, datetime.now(FUSO))
    if tipo not in dict(TIPOS_REL):
        tipo = "todos"
    # limites do mês no fuso local, convertidos para UTC (como o banco guarda)
    ini = datetime(ano, m, 1, tzinfo=FUSO).astimezone(timezone.utc)
    fim = datetime(ano + (m == 12), m % 12 + 1, 1, tzinfo=FUSO).astimezone(timezone.utc)

    dias: dict = {}

    def linha(dt):
        return dias.setdefault(_local(dt).date(), {"entrada": 0, "saida": 0, "itens": 0, "etiquetas": 0})

    guias, etqs = [], []
    if tipo in ("todos", "guias"):
        guias = db.scalars(select(Guia).options(selectinload(Guia.itens), selectinload(Guia.operador))
                           .where(Guia.criado_em >= ini, Guia.criado_em < fim).order_by(Guia.criado_em)).all()
        for g in guias:
            l = linha(g.criado_em)
            l["entrada" if "ENTRADA" in g.tipo else "saida"] += 1
            l["itens"] += len(g.itens)
            g.data = hora_local(g.criado_em)
    if tipo in ("todos", "etiquetas"):  # inclui as removidas da lista de recentes (histórico completo)
        etqs = db.scalars(select(Etiqueta).options(selectinload(Etiqueta.equipamento), selectinload(Etiqueta.operador))
                          .where(Etiqueta.criado_em >= ini, Etiqueta.criado_em < fim)
                          .order_by(Etiqueta.criado_em)).all()
        for e in etqs:
            linha(e.criado_em)["etiquetas"] += 1
            e.data = hora_local(e.criado_em)

    tot = {k: sum(l[k] for l in dias.values()) for k in ("entrada", "saida", "itens", "etiquetas")}
    tot["guias"] = tot["entrada"] + tot["saida"]
    tabela = [{"dia": d.strftime("%d/%m/%Y"), **l} for d, l in sorted(dias.items())]
    return pagina(request, "relatorios.html", user, mes=f"{ano}-{m:02d}", tipo=tipo, opcoes=TIPOS_REL,
                  tipo_txt=dict(TIPOS_REL)[tipo], titulo=f"{MESES[m - 1]} de {ano}", tot=tot,
                  tabela=tabela, guias=guias, etiquetas=etqs)


# ---------- equipamentos ----------
@router.get("/equipamentos/buscar")
def equipamento_buscar(patrimonio: str = "", db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    """Usada pelo formulário de guia: devolve os dados do equipamento com esse patrimônio, se existir."""
    p = patrimonio.strip()[:100]
    eq = db.scalar(select(Equipamento).where(func.lower(Equipamento.patrimonio) == p.lower())) if p else None
    if not eq:
        return {"encontrado": False}
    return {"encontrado": True, "tipo": eq.tipo, "modelo": eq.modelo or "", "serial": eq.serial or "",
            "hostname": eq.hostname or "", "ip": eq.ip or "", "localidade": eq.localidade or ""}


@router.get("/equipamentos")
def equipamentos(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    stmt = select(Equipamento).order_by(Equipamento.id.desc()).limit(200)
    if q.strip():
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(Equipamento.patrimonio.ilike(like), Equipamento.serial.ilike(like),
                              Equipamento.hostname.ilike(like), Equipamento.ip.ilike(like)))
    return pagina(request, "equipamentos.html", user, itens=db.scalars(stmt).all(), q=q)