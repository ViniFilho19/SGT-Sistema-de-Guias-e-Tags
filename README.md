# Etiquetas e Guias – API (FastAPI)

## Rodar
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env        # edite SECRET_KEY
    python criar_admin.py       # cria o primeiro administrador
    uvicorn app.main:app --reload

Sistema: http://localhost:8000  ·  API (Swagger): http://localhost:8000/docs

## Interface web
Telas em `app/templates` (Jinja2) e estilo em `app/static/app.css`, no padrão visual do painel SAS:
login, painel, etiquetas (com QR e impressão), nova guia, guias emitidas (2 vias para impressão) e equipamentos.
Sessão por cookie HttpOnly + SameSite=Strict; em produção com HTTPS defina `COOKIE_SEGURO=true`.
CSP restritiva (`script-src 'self'`): o único JS é `static/print.js` (botão imprimir).

## API REST (prefixo `/api`)
| Método | Rota | Descrição |
|---|---|---|
| POST | /api/auth/login | login (form: username, password) -> token JWT |
| GET | /api/auth/me | usuário logado |
| POST | /api/users | criar usuário (admin) |
| GET/POST | /api/equipamentos | listar (?q=, ?tipo=, skip, limit) / cadastrar |
| GET/PUT/DELETE | /api/equipamentos/{id} | consultar / atualizar / excluir (admin) |
| POST | /api/etiquetas | gera etiqueta (cria ou atualiza o equipamento pelo patrimônio) |
| GET | /api/etiquetas | histórico de etiquetas |
| GET | /api/etiquetas/equipamento/{id}/qrcode.png | imagem do QR code |
| POST/GET | /api/guias | criar guia com itens / listar (?tipo=, ?chamado=) |
| GET | /api/guias/{id} | consultar guia |

Enviar o token em todas as rotas (exceto login): `Authorization: Bearer <token>`

## Tabelas
users, equipamentos (patrimônio único), etiquetas (histórico), guias, guia_itens.

## Próximos passos
PostgreSQL (DATABASE_URL), migrações com Alembic, limite de tentativas de login,
HTTPS no proxy (nginx/Caddy) e as telas HTML (Jinja2) e PDF (ReportLab/WeasyPrint).
