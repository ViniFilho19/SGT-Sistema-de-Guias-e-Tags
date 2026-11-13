from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .migracoes import migrar
from .routers import auth, equipamentos, etiquetas, guias
from . import web


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # em produção, prefira migrações com Alembic
    migrar(engine)
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
for r in (auth.router, equipamentos.router, etiquetas.router, guias.router):
    app.include_router(r, prefix="/api")
