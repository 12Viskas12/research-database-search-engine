from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@db:5432/search"
    redis_url: str = "redis://redis:6379"
    bot_token: str = ""
    upload_dir: str = "/data/uploads"


settings = Settings()
