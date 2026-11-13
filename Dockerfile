FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Bahia

WORKDIR /app

# Dependências primeiro (aproveita cache de camadas)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Código da aplicação
COPY app ./app
COPY criar_admin.py .

# Usuário sem privilégios + pasta do banco SQLite
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data
USER appuser

ENV DATABASE_URL=sqlite:////app/data/etiquetas.db

EXPOSE 5005

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5005/docs', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5005", "--proxy-headers"]
