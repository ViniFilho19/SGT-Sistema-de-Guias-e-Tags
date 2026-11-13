# Etiquetas e Guias – API (FastAPI)

## Rodar
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env        # edite SECRET_KEY
    python criar_admin.py       # cria o primeiro administrador
    uvicorn app.main:app --reload --port 5005   # ou: .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 5005

Sistema: http://localhost:5005  ·  API (Swagger): http://localhost:5005/docs

## Interface web
Telas em `app/templates` (Jinja2) estilizadas com **Tailwind CSS v4**. O CSS de origem fica em `app/assets/tailwind.css`
e é compilado para `app/static/app.css` (arquivo gerado, versionado para o sistema rodar sem build).

Para alterar o visual, baixe o Tailwind CLI standalone (não precisa de Node) em `tools/` e recompile:

    mkdir tools
    curl -L -o tools/tailwindcss.exe https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.11/tailwindcss-windows-x64.exe
    tools	ailwindcss.exe -i app/assets/tailwind.css -o app/static/app.css --minify          # gera uma vez
    tools	ailwindcss.exe -i app/assets/tailwind.css -o app/static/app.css --watch           # recompila ao salvar

Telas:
login, painel, etiquetas (com QR e impressão), nova guia, guias emitidas (2 vias para impressão) e equipamentos.
Sessão por cookie HttpOnly + SameSite=Strict; em produção com HTTPS defina `COOKIE_SEGURO=true`.
CSP restritiva (`script-src 'self'`): sem JS inline; `static/app.js` cuida de imprimir e das confirmações (`data-confirm`).

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
