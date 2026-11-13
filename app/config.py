from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent          # pasta do projeto
PASTA_DADOS = RAIZ / "data"
PASTA_DADOS.mkdir(exist_ok=True)


class Settings(BaseSettings):
    # Caminho absoluto: o banco fica sempre em data/, de qualquer pasta que o sistema seja iniciado
    database_url: str = f"sqlite:///{(PASTA_DADOS / 'etiquetas.db').as_posix()}"
    secret_key: str = "INSEGURO-troque-no-env"
    access_token_minutes: int = 480
    cookie_seguro: bool = False  # True quando estiver atrás de HTTPS
    model_config = SettingsConfigDict(env_file=RAIZ / ".env")


settings = Settings()
