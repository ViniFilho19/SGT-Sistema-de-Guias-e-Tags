"""Telas HTML (renderizadas no servidor, sem JavaScript de aplicação)."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_, select, true, update
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .database import get_db
from .models import Equipamento, Etiqueta, Guia, GuiaItem, User
from .pdf import pdf_mes, pdf_patrimonio
from .planilha import planilha_mes, planilha_patrimonio
from .routers.etiquetas import gerar_etiqueta, qr_data_uri, texto_qr
from .routers.guias import criar as criar_guia, equipamento_por_patrimonio
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
ARQ_LOCALIDADES = Path(__file__).parent / "localidades.txt"


def localidades() -> list[str]:
    """Sugestões de localidade (app/localidades.txt), relidas a cada uso para refletir edições."""
    try:
        linhas = ARQ_LOCALIDADES.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return list(dict.fromkeys(" ".join(l.split()) for l in linhas if l.strip() and not l.lstrip().startswith("#")))


templates.env.globals["localidades"] = localidades
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
def _form_guia(request, user, v=None, linhas=None, erro=None, status=200, divergencias=None, assinatura=""):
    v = v or {"tipo": SAIDA, "motivo": "", "chamado": "", "remetente": "", "destinatario": "", "responsavel": ""}
    linhas = linhas or [{c: "" for c in COLS_ITEM} | {"tipo_equipamento": "Computador"} for _ in range(LINHAS)]
    return pagina(request, "guias_nova.html", user, status, v=v, linhas=linhas, tipos=TIPOS, erro=erro,
                  tipos_guia=[SAIDA, ENTRADA], motivos=MOTIVOS, divergencias=divergencias, assinatura=assinatura)


# campo da guia -> (atributo do equipamento, rótulo)
CAMPOS_CADASTRO = {"tipo_equipamento": ("tipo", "Tipo"), "modelo": ("modelo", "Modelo"),
                   "serial": ("serial", "Nº série"), "hostname": ("hostname", "Hostname"), "ip": ("ip", "IP")}


def _divergencias(db: Session, itens) -> list[dict]:
    """Compara cada equipamento da guia com o cadastro (pelo patrimônio) e lista o que foi digitado diferente."""
    res, vistos = [], set()
    for item in itens:
        eq = equipamento_por_patrimonio(db, item.patrimonio)
        if not eq or eq.id in vistos:
            continue
        vistos.add(eq.id)
        mudancas = []
        for campo, (attr, rotulo) in CAMPOS_CADASTRO.items():
            novo = (getattr(item, campo) or "").strip()
            atual = (getattr(eq, attr) or "").strip()
            if novo and novo.casefold() != atual.casefold():
                mudancas.append({"attr": attr, "rotulo": rotulo, "atual": atual, "novo": novo})
        if mudancas:
            res.append({"eq": eq, "patrimonio": eq.patrimonio, "mudancas": mudancas})
    return res


def _assinatura(divs: list[dict]) -> str:
    """Identifica exatamente as mudanças mostradas; se o formulário mudar, a confirmação é pedida de novo."""
    base = json.dumps([[d["eq"].id, [[m["attr"], m["novo"]] for m in d["mudancas"]]] for d in divs])
    return hashlib.sha256(base.encode()).hexdigest()[:16]


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

    # dados diferentes do cadastro de equipamentos: pergunta antes de corrigir o cadastro
    divs = _divergencias(db, dados.itens)
    escolha, assinatura = str(f.get("cadastro", "")), _assinatura(divs) if divs else ""
    if divs and (escolha not in ("atualizar", "manter") or str(f.get("assinatura", "")) != assinatura):
        return _form_guia(request, user, v, linhas, divergencias=divs, assinatura=assinatura)
    atualizou = divs and escolha == "atualizar"
    if atualizou:
        for d in divs:
            for m in d["mudancas"]:
                setattr(d["eq"], m["attr"], m["novo"])
            d["eq"].atualizado_em = datetime.now(timezone.utc)
    guia = criar_guia(dados, db, user)  # o commit também grava as correções do cadastro
    return RedirectResponse(f"/guias/{guia.id}" + ("?ok=cadastro" if atualizou else ""), 303)


SAIDA, ENTRADA = "GUIA DE SAÍDA", "GUIA DE ENTRADA"
E_SAIDA = Guia.tipo.like(SAIDA + "%")  # saída comum ou desfazimento
PRONTA = or_(Guia.status.is_(None), Guia.status == "pronta")
FILTROS = {  # aba -> (rótulo, condição)
    "todas": ("Todas", None),
    "prontas": ("Prontas p/ entrega", E_SAIDA & PRONTA),
    "entregues": ("Entregues", E_SAIDA & (Guia.status == "entregue")),
    "entrada": ("Entrada", Guia.tipo.like(ENTRADA + "%")),
}
AVISOS_GUIA = {"entregue": "Entrega registrada.", "reaberta": "Guia voltou para “pronta”.",
               "cadastro": "Guia emitida e cadastro do equipamento corrigido."}
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
          "editado": "Usuário atualizado.",
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


def _ass_edicao(alvo_id: int, novos: dict) -> str:
    """Identifica exatamente as mudanças revisadas; se o formulário mudar, a confirmação é pedida de novo."""
    base = json.dumps([alvo_id, sorted(novos.items()), settings.secret_key])
    return hashlib.sha256(base.encode()).hexdigest()[:20]


def _form_edicao(request, user, alvo, v, erro=None, mudancas=None, assinatura="", status=200):
    return pagina(request, "usuario_editar.html", user, status, alvo=alvo, v=v, papeis=PAPEIS, erro=erro,
                  mudancas=mudancas, assinatura=assinatura)


@router.get("/usuarios/{id_}/editar")
def usuario_editar(request: Request, id_: int, db: Session = Depends(get_db), user: User = Depends(admin_web)):
    alvo = _alvo(db, id_)
    v = {"username": alvo.username, "nome": alvo.nome, "papel": alvo.papel, "ativo": alvo.ativo}
    return _form_edicao(request, user, alvo, v)


@router.post("/usuarios/{id_}/editar")
def usuario_editar_salvar(request: Request, id_: int, username: str = Form(""), nome: str = Form(""),
                          papel: str = Form(""), ativo: str = Form(""), senha: str = Form(""), senha2: str = Form(""),
                          confirmar: str = Form(""), db: Session = Depends(get_db), user: User = Depends(admin_web)):
    alvo = _alvo(db, id_)
    proprio = alvo.id == user.id
    v = {"username": username.strip(), "nome": " ".join(nome.split()),
         "papel": alvo.papel if proprio else papel, "ativo": alvo.ativo if proprio else ativo == "1"}

    def erro(msg):
        return _form_edicao(request, user, alvo, v, erro=msg, status=422)

    if v["papel"] not in PAPEIS:
        return erro(ERROS["papel"])
    try:
        UserCreate(username=v["username"], nome=v["nome"], senha="x" * 8, papel=v["papel"])
    except ValidationError as e:
        campos = sorted({str(x["loc"][0]) for x in e.errors()})
        return erro("Verifique os campos: " + ", ".join(campos) + " (login: 3 a 50 letras, números, . _ -).")
    if senha or senha2:
        if not _senha_ok(senha):
            return erro(ERROS["senha"])
        if senha != senha2:
            return erro("A nova senha e a confirmação não conferem.")
    if v["username"].lower() != alvo.username.lower() and db.scalar(
            select(User.id).where(func.lower(User.username) == v["username"].lower(), User.id != alvo.id)):
        return erro("Já existe um usuário com esse login.")

    mudancas = []
    if v["nome"] != alvo.nome:
        mudancas.append(("Nome", alvo.nome, v["nome"]))
    if v["username"] != alvo.username:
        mudancas.append(("Usuário (login)", alvo.username, v["username"]))
    if v["papel"] != alvo.papel:
        mudancas.append(("Papel", alvo.papel.capitalize(), v["papel"].capitalize()))
    if v["ativo"] != alvo.ativo:
        mudancas.append(("Status", "Ativo" if alvo.ativo else "Inativo", "Ativo" if v["ativo"] else "Inativo"))
    if senha:
        mudancas.append(("Senha", "(atual)", "será redefinida"))
    if not mudancas:
        return erro("Nenhuma alteração para salvar.")

    novos = {**v, "senha": senha}
    assinatura = _ass_edicao(alvo.id, novos)
    if confirmar != assinatura:  # 1ª confirmação: revisar "como está" x "como fica"
        return _form_edicao(request, user, alvo, {**v, "senha": senha}, mudancas=mudancas, assinatura=assinatura)

    alvo.nome, alvo.username, alvo.papel, alvo.ativo = v["nome"], v["username"], v["papel"], v["ativo"]
    if senha:
        alvo.senha_hash = hash_senha(senha)
    db.commit()
    return RedirectResponse("/usuarios?ok=editado", 303)


# ---------- minha senha (qualquer usuário) ----------
@router.get("/minha-senha")
def minha_senha(request: Request, ok: str = "", user: User = Depends(usuario_web)):
    return pagina(request, "minha_senha.html", user, ok="Senha alterada com sucesso." if ok else None)


@router.post("/minha-senha")
def minha_senha_salvar(request: Request, atual: str = Form(""), nova: str = Form(""), nova2: str = Form(""),
                       db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    def erro(msg, status=422):
        return pagina(request, "minha_senha.html", user, status, erro=msg)

    chave = f"senha|{user.id}"
    if bloqueado(chave):
        return erro("Muitas tentativas com a senha atual errada. Aguarde 15 minutos.", 429)
    if not confere_senha(atual, user.senha_hash):
        registrar_falha(chave)
        return erro("A senha atual está incorreta.", 401)
    limpar_falhas(chave)
    if not _senha_ok(nova):
        return erro(ERROS["senha"])
    if nova != nova2:
        return erro("A nova senha e a confirmação não conferem.")
    if nova == atual:
        return erro("A nova senha deve ser diferente da atual.")
    user.senha_hash = hash_senha(nova)
    db.commit()
    return RedirectResponse("/minha-senha?ok=1", 303)


# ---------- relatórios ----------
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
TIPOS_REL = [("todos", "Guias e etiquetas"), ("guias", "Todas as guias (entrada e saída)"),
             ("saida", "Guias de saída"), ("entrada", "Guias de entrada"), ("etiquetas", "Etiquetas")]
STATUS_REL = [("", "Todos"), ("pronta", "Prontas (aguardando entrega)"), ("entregue", "Entregues")]
TIPOS_ANTIGOS = {"prontas": ("saida", "pronta"), "enviadas": ("saida", "entregue")}  # links antigos
PERIODOS = [("mes", "Mês"), ("semestre", "Semestre"), ("ano", "Ano"), ("personalizado", "Período personalizado (datas)")]


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


def _norm_serial(s: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def _sql_serial(col):
    """Nº de série sem espaços, hífens e barras, em maiúsculas (mesma regra de _norm_serial)."""
    for ch in (" ", "-", "/", "."):
        col = func.replace(col, ch, "")
    return func.upper(col)


def _tokens_local(txt: str | None) -> set[str]:
    import unicodedata
    t = unicodedata.normalize("NFKD", (txt or "").upper()).encode("ascii", "ignore").decode()
    t = re.sub(r"\b\d+\s*[AO°º]?\b|[^A-Z ]", " ", t)  # tira "02ª", "6º", pontuação
    return {w for w in t.split() if w not in {"DE", "DA", "DO", "DAS", "DOS", "E", "BA"}}


def _mesmo_local(a: str | None, b: str | None) -> bool:
    ta, tb = _tokens_local(a), _tokens_local(b)
    sede = lambda t: "SEDE" in t or {"SERVICE", "DESK"} <= t  # o Service Desk fica na sede
    return bool(ta and tb) and (ta <= tb or tb <= ta or (sede(ta) and sede(tb)))


def _historico_patrimonio(db: Session, termo: str) -> dict:
    """Movimentações (guias de entrada e saída) e etiquetas de uma máquina, buscada por patrimônio ou nº de série."""
    p = termo.strip()[:100]
    eq, achado_por = equipamento_por_patrimonio(db, p), "patrimônio"
    ns = _norm_serial(p)
    if not eq and len(ns) >= 5:
        eq = db.scalars(select(Equipamento).where(_sql_serial(Equipamento.serial) == ns).order_by(Equipamento.id)).first()
        achado_por = "nº de série" if eq else ""
    pats = {x for x in (p, eq.patrimonio if eq else None) if x}
    seriais = {x for x in (ns, _norm_serial(eq.serial) if eq else "") if len(x) >= 5}
    conds = []
    for x in pats:
        conds += [func.lower(GuiaItem.patrimonio) == x.lower()]
        if x.lstrip("0"):
            conds.append(func.ltrim(GuiaItem.patrimonio, "0") == x.lstrip("0"))
    conds += [_sql_serial(GuiaItem.serial) == s for s in seriais]
    if eq:
        conds.append(GuiaItem.equipamento_id == eq.id)
    cond = or_(*conds)
    itens = db.scalars(select(GuiaItem).options(selectinload(GuiaItem.guia).selectinload(Guia.operador))
                       .where(cond)).all()
    movs = sorted({i.guia_id: i for i in itens}.values(), key=lambda i: i.guia.criado_em, reverse=True)
    for i in movs:
        i.data = hora_local(i.guia.criado_em)
        i.entregue_txt = hora_local(i.guia.entregue_em) if i.guia.entregue_em else ""
    etqs = []
    if eq:
        etqs = db.scalars(select(Etiqueta).options(selectinload(Etiqueta.operador))
                          .where(Etiqueta.equipamento_id == eq.id).order_by(Etiqueta.criado_em.desc())).all()
        for e in etqs:
            e.data = hora_local(e.criado_em)
    entradas = sum(1 for i in movs if "ENTRADA" in i.guia.tipo)
    atual = movs[0].guia.destinatario if movs else None  # destino da última guia
    divergente = bool(atual and eq and eq.localidade and not _mesmo_local(atual, eq.localidade))
    return {"busca": p, "eq": eq, "achado_por": achado_por, "movs": movs, "etiquetas": etqs, "entradas": entradas,
            "saidas": len(movs) - entradas, "atual": atual, "atual_desde": movs[0].data if movs else "",
            "divergente": divergente}


@router.get("/relatorios")
def relatorios(request: Request, mes: str = "", tipo: str = "todos", patrimonio: str = "", periodo: str = "mes",
               semestre: str = "", ano: str = "", de: str = "", ate: str = "", status: str = "",
               db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    emitido = datetime.now(FUSO).strftime("%d/%m/%Y às %H:%M")
    if patrimonio.strip():
        return pagina(request, "relatorios.html", user, hist=_historico_patrimonio(db, patrimonio), tipo=tipo,
                      opcoes=TIPOS_REL, periodos=PERIODOS, semestres=_semestres(), anos=_anos(), status_opcoes=STATUS_REL, status_entrega=status,
                      patrimonio=patrimonio.strip(), emitido=emitido, **_periodo(periodo, mes, semestre, ano, de, ate))
    return pagina(request, "relatorios.html", user, opcoes=TIPOS_REL, periodos=PERIODOS, emitido=emitido,
                  semestres=_semestres(), anos=_anos(), status_opcoes=STATUS_REL,
                  **_relatorio_mes(db, mes, tipo, periodo, semestre, ano, de, ate, status))


def _anos() -> list[str]:
    a = datetime.now(FUSO).year
    return [str(x) for x in range(a, a - 6, -1)]


def _semestres() -> list[tuple[str, str]]:
    return [(f"{a}-{s}", f"{s}º semestre de {a}") for a in _anos() for s in (2, 1)]


FORMATOS = {"planilha": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          planilha_mes, planilha_patrimonio),
            "pdf": ("pdf", "application/pdf", pdf_mes, pdf_patrimonio)}


@router.get("/relatorios/{formato}")
def relatorios_arquivo(formato: str, mes: str = "", tipo: str = "todos", patrimonio: str = "", periodo: str = "mes",
                       semestre: str = "", ano: str = "", de: str = "", ate: str = "", status: str = "",
                       db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    """Mesmo conteúdo do relatório na tela, para baixar em planilha Excel (.xlsx) ou PDF."""
    if formato not in FORMATOS:
        raise HTTPException(404, "Formato não disponível")
    ext, mime, gerar_mes, gerar_pat = FORMATOS[formato]
    if patrimonio.strip():
        h = _historico_patrimonio(db, patrimonio)
        conteudo = gerar_pat(h, user.nome)
        nome = f"movimentacoes-maquina-{re.sub(r'[^0-9A-Za-z]', '', h['busca'])[:30] or 'busca'}.{ext}"
    else:
        r = _relatorio_mes(db, mes, tipo, periodo, semestre, ano, de, ate, status)
        conteudo = gerar_mes(r, user.nome)
        nome = f"relatorio-sgt-{r['nome_arquivo']}.{ext}"
    return Response(conteudo, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _data(txt: str):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except ValueError:
        return None


def _periodo(periodo: str, mes: str, semestre: str, ano: str, de: str, ate: str) -> dict:
    """Intervalo [ini, fim) em datas locais + título, a partir do tipo de período escolhido."""
    hoje = datetime.now(FUSO).date()
    periodo = periodo if periodo in dict(PERIODOS) else "mes"
    if periodo == "semestre":
        try:
            a, sm = (int(x) for x in semestre.split("-"))
            assert 2000 <= a <= 2100 and sm in (1, 2)
        except (ValueError, AssertionError):
            a, sm = hoje.year, 1 if hoje.month <= 6 else 2
        ini, fim = date(a, 1 if sm == 1 else 7, 1), (date(a, 7, 1) if sm == 1 else date(a + 1, 1, 1))
        titulo, semestre = f"{sm}º semestre de {a}", f"{a}-{sm}"
    elif periodo == "ano":
        a = int(ano) if ano.isdigit() and 2000 <= int(ano) <= 2100 else hoje.year
        ini, fim, titulo, ano = date(a, 1, 1), date(a + 1, 1, 1), f"ano de {a}", str(a)
    elif periodo == "personalizado":
        d1, d2 = _data(de) or hoje.replace(day=1), _data(ate) or hoje
        d1, d2 = min(d1, d2), max(d1, d2)
        d1 = max(d1, d2 - timedelta(days=366 * 3))  # no máximo 3 anos
        ini, fim = d1, d2 + timedelta(days=1)
        titulo, de, ate = f"{d1:%d/%m/%Y} a {d2:%d/%m/%Y}", d1.isoformat(), d2.isoformat()
    else:
        a, m = _parse_mes(mes, hoje)
        ini, fim = date(a, m, 1), date(a + (m == 12), m % 12 + 1, 1)
        titulo, mes = f"{MESES[m - 1]} de {a}", f"{a}-{m:02d}"
    return {"periodo": periodo, "ini": ini, "fim": fim, "titulo": titulo, "mes": mes or f"{hoje:%Y-%m}",
            "semestre": semestre or f"{hoje.year}-{1 if hoje.month <= 6 else 2}", "ano": ano or str(hoje.year),
            "de": de or hoje.replace(day=1).isoformat(), "ate": ate or hoje.isoformat()}


def _relatorio_mes(db: Session, mes: str = "", tipo: str = "todos", periodo: str = "mes", semestre: str = "",
                   ano: str = "", de: str = "", ate: str = "", status: str = "") -> dict:
    if tipo in TIPOS_ANTIGOS:
        tipo, status = TIPOS_ANTIGOS[tipo]
    if tipo not in dict(TIPOS_REL):
        tipo = "todos"
    if status not in dict(STATUS_REL) or tipo in ("entrada", "etiquetas"):
        status = ""  # status (pronta/entregue) só existe em guias de saída
    p = _periodo(periodo, mes, semestre, ano, de, ate)
    # limites no fuso local, convertidos para UTC (como o banco guarda)
    ini = datetime(p["ini"].year, p["ini"].month, p["ini"].day, tzinfo=FUSO).astimezone(timezone.utc)
    fim = datetime(p["fim"].year, p["fim"].month, p["fim"].day, tzinfo=FUSO).astimezone(timezone.utc)
    por_mes = (p["fim"] - p["ini"]).days > 62  # períodos longos: agrupa por mês
    com_guias, com_etq = tipo != "etiquetas", tipo in ("todos", "etiquetas")

    grupos: dict = {}

    def linha(dt):
        d = _local(dt).date()
        return grupos.setdefault((d.year, d.month) if por_mes else d,
                                 {"entrada": 0, "saida": 0, "itens": 0, "etiquetas": 0})

    guias, etqs = [], []
    if com_guias:
        q = (select(Guia).options(selectinload(Guia.itens), selectinload(Guia.operador))
             .where(Guia.criado_em >= ini, Guia.criado_em < fim).order_by(Guia.criado_em))
        if tipo == "saida" or status:
            q = q.where(E_SAIDA)
        elif tipo == "entrada":
            q = q.where(Guia.tipo.like(ENTRADA + "%"))
        if status == "pronta":
            q = q.where(PRONTA)
        elif status == "entregue":
            q = q.where(Guia.status == "entregue")
        guias = db.scalars(q).all()
        for g in guias:
            l = linha(g.criado_em)
            l["entrada" if "ENTRADA" in g.tipo else "saida"] += 1
            l["itens"] += len(g.itens)
            g.data = hora_local(g.criado_em)
    if com_etq:  # inclui as removidas da lista de recentes (histórico completo)
        etqs = db.scalars(select(Etiqueta).options(selectinload(Etiqueta.equipamento), selectinload(Etiqueta.operador))
                          .where(Etiqueta.criado_em >= ini, Etiqueta.criado_em < fim)
                          .order_by(Etiqueta.criado_em)).all()
        for e in etqs:
            linha(e.criado_em)["etiquetas"] += 1
            e.data = hora_local(e.criado_em)

    tot = {k: sum(l[k] for l in grupos.values()) for k in ("entrada", "saida", "itens", "etiquetas")}
    tot["guias"] = tot["entrada"] + tot["saida"]
    if por_mes:
        tabela = [{"dia": f"{MESES[m - 1].capitalize()}/{a}", **l} for (a, m), l in sorted(grupos.items())]
    else:
        tabela = [{"dia": d.strftime("%d/%m/%Y"), **l} for d, l in sorted(grupos.items())]
    campos = {"periodo": p["periodo"], "tipo": tipo, "status": status, "mes": p["mes"], "semestre": p["semestre"], "ano": p["ano"],
              "de": p["de"], "ate": p["ate"]}
    ultimo = p["fim"] - timedelta(days=1)
    return {**p, "tipo": tipo, "status_entrega": status,
            "tipo_txt": dict(TIPOS_REL)[tipo] + (f" · {dict(STATUS_REL)[status]}" if status else ""), "tot": tot, "tabela": tabela, "guias": guias,
            "etiquetas": etqs, "com_guias": com_guias, "com_etq": com_etq, "grupo": "Mês" if por_mes else "Dia",
            "qs": urlencode(campos), "nome_arquivo": f"{p['ini']:%Y-%m-%d}_a_{ultimo:%Y-%m-%d}-{tipo}{'-' + status if status else ''}"}


# ---------- equipamentos ----------
@router.get("/equipamentos/buscar")
def equipamento_buscar(patrimonio: str = "", db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    """Usada pelo formulário de guia: devolve os dados do equipamento com esse patrimônio, se existir."""
    eq = equipamento_por_patrimonio(db, patrimonio)
    if not eq:
        return {"encontrado": False}
    return {"encontrado": True, "tipo": eq.tipo, "modelo": eq.modelo or "", "serial": eq.serial or "",
            "hostname": eq.hostname or "", "ip": eq.ip or "", "localidade": eq.localidade or "",
            "mascara": eq.mascara or "", "gateway": eq.gateway or "", "patrimonio": eq.patrimonio or ""}


@router.get("/equipamentos")
def equipamentos(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(usuario_web)):
    stmt = select(Equipamento).order_by(Equipamento.id.desc()).limit(200)
    if q.strip():
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(Equipamento.patrimonio.ilike(like), Equipamento.serial.ilike(like),
                              Equipamento.hostname.ilike(like), Equipamento.ip.ilike(like)))
    return pagina(request, "equipamentos.html", user, itens=db.scalars(stmt).all(), q=q)