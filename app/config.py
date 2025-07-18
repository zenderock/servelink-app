from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
import json
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "/dev/push"
    app_description: str = "Build and deploy your Python app without touching a server."
    url_scheme: str = "http"
    hostname: str = "localhost"
    deploy_domain: str = "localhost"
    github_app_id: str = ""
    github_app_name: str = ""
    github_app_private_key: str = ""
    github_app_webhook_secret: str = ""
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    resend_api_key: str = ""
    email_logo: str = ""
    email_sender_name: str = ""
    email_sender_address: str = ""
    secret_key: str = "secret-key"
    encryption_key: str = "encryption-key"
    postgres_host: str = "pgsql"
    postgres_user: str = "devpush"
    postgres_password: str = "devpush"
    postgres_db: str = "devpush"
    redis_url: str = "redis://redis:6379"
    docker_host: str = "tcp://docker-proxy:2375"
    upload_dir: str = "/upload"
    traefik_config_dir: str = "/data/traefik"
    frameworks: list[dict] = []
    deployment_timeout: int = 90
    db_echo: bool = False
    env: str = "development"
    log_level: str = "WARNING"

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings():
    settings = Settings()

    frameworks_file = Path("settings/frameworks.json")
    try:
        settings.frameworks = json.loads(frameworks_file.read_text(encoding="utf-8"))
    except Exception:
        settings.frameworks = []

    return settings
