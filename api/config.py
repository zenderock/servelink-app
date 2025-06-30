from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "/dev/push"
    app_description: str = "Build and deploy your Python app without touching a server."
    url_scheme: str = "http"
    base_domain: str = "localhost"
    github_app_id: str
    github_app_name: str
    github_app_private_key: str
    github_app_webhook_secret: str
    github_app_client_id: str
    github_app_client_secret: str
    secret_key: str
    encryption_key: str
    postgres_user: str = "devpush"
    postgres_password: str = "devpush"
    postgres_db: str = "devpush"
    templates_auto_reload: str = "false"
    db_echo: bool = False
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings():
    return Settings()