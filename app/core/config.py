from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@db:5432/search"
    redis_url: str = "redis://redis:6379"
    bot_token: str = ""
    upload_dir: str = "/data/uploads"
    site_url: str = "http://localhost:8000"
    admin_username: str = "admin"
    admin_password: str = ""
    quota_user: int = 3
    quota_vip: int = 50
    session_days: int = 14
    invite_hours: int = 72
    cookie_secure: bool = False


settings = Settings()
