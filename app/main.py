from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .migracoes import migrar
from .routers import auth, equipamentos, etiquetas, guias
from . import almoxarifado, web


def admin_inicial():
    """Cria o administrador do .env (ADMIN_USUARIO/ADMIN_SENHA) se o banco ainda não tiver nenhum admin ativo."""
    from sqlalchemy import select
    from .config import settings
    from .models import User
    from .security import hash_senha
    usuario, senha = settings.admin_usuario.strip(), settings.admin_senha
    if not usuario or not senha:
        return
    if len(senha) < 8:
        print("ADMIN_SENHA ignorada: use pelo menos 8 caracteres.")
        return
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.papel == "admin", User.ativo.is_(True)).limit(1)):
            return
        u = db.scalar(select(User).where(User.username == usuario))
        if u:
            u.papel, u.ativo, u.senha_hash = "admin", True, hash_senha(senha)
        else:
            db.add(User(username=usuario, nome=settings.admin_nome, papel="admin", senha_hash=hash_senha(senha)))
        db.commit()
        print(f"Administrador inicial '{usuario}' criado.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # em produção, prefira migrações com Alembic
    migrar(engine)
    admin_inicial()
    yield


app = FastAPI(title="SGT - Etiquetas e Guias - DETRAN/BA", lifespan=lifespan)

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "frame-ancestors 'none'; form-action 'self'; base-uri 'none'")


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith(("/docs", "/openapi", "/redoc")):  # o Swagger precisa de scripts externos
        resp.headers["Content-Security-Policy"] = CSP
    return resp


@app.exception_handler(HTTPException)
async def erro_http(request: Request, exc: HTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:  # sessão expirada -> login
        return RedirectResponse(exc.headers["Location"], 303)
    from fastapi.exception_handlers import http_exception_handler
    return await http_exception_handler(request, exc)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(web.router)
app.include_router(almoxarifado.router)
for r in (auth.router, equipamentos.router, etiquetas.router, guias.router):
    app.include_router(r, prefix="/api")
