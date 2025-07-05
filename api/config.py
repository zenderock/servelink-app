from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
import json
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "/dev/push"
    app_description: str = "Build and deploy your Python app without touching a server."
    url_scheme: str = "http"
    base_domain: str = "localhost"
    github_app_id: str = ""
    github_app_name: str = ""
    github_app_private_key: str = ""
    github_app_webhook_secret: str = ""
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    secret_key: str = "secret-key"
    encryption_key: str = "encryption-key"
    postgres_user: str = "devpush"
    postgres_password: str = "devpush"
    postgres_db: str = "devpush"
    redis_url: str = "redis://redis:6379"
    docker_host: str = "tcp://docker-proxy:2375"
    upload_dir: str = "/app/static/upload"
    traefik_config_dir: str = "/data/traefik"
    frameworks: list[dict] = []
    deployment_timeout: int = 90
    templates_auto_reload: str = "false"
    db_echo: bool = False
    env: str = "development"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings():
    settings = Settings()

    frameworks_file = Path("settings/frameworks.json")
    try:
        settings.frameworks = json.loads(frameworks_file.read_text(encoding="utf-8"))
    except Exception:
        settings.frameworks = []
    
    return settings