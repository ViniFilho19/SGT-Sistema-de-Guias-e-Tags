from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./etiquetas.db"
    secret_key: str = "INSEGURO-troque-no-env"
    access_token_minutes: int = 480
    cookie_seguro: bool = False  # True quando estiver atrás de HTTPS
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
