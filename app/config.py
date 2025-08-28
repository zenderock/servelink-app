from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
import json
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "/dev/push"
    app_description: str = (
        "An open-source platform to build and deploy any app from GitHub."
    )
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
    postgres_user: str = "devpush-app"
    postgres_password: str = "devpush"
    postgres_db: str = "devpush"
    redis_url: str = "redis://redis:6379"
    docker_host: str = "tcp://docker-proxy:2375"
    upload_dir: str = "/upload"
    traefik_config_dir: str = "/data/traefik"
    default_cpu_quota: int = 100000
    default_memory_mb: int = 4096
    presets: list[dict] = []
    runtimes: list[dict] = []
    job_timeout: int = 320
    job_completion_wait: int = 300
    deployment_timeout: int = 300
    db_echo: bool = False
    log_level: str = "WARNING"
    env: str = "development"
    access_rules_path: str = "settings/access.json"
    access_denied_message: str = "Sign-in not allowed for this email."
    access_denied_webhook: str = ""
    login_alert_title: str = ""
    login_alert_description: str = ""
    server_ip: str = "127.0.0.1"

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings():
    settings = Settings()

    presets_file = Path("settings/presets.json")
    runtimes_file = Path("settings/runtimes.json")
    try:
        settings.presets = json.loads(presets_file.read_text(encoding="utf-8"))
        settings.runtimes = json.loads(runtimes_file.read_text(encoding="utf-8"))
    except Exception:
        settings.presets = []
        settings.runtimes = []

    return settings
