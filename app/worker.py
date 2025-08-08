import logging
from arq.connections import RedisSettings
from tasks.deploy import deploy
from tasks.cleanup import (
    cleanup_user,
    cleanup_team,
    cleanup_project,
    cleanup_inactive_deployments,
)

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class WorkerSettings:
    functions = [
        deploy,
        cleanup_user,
        cleanup_team,
        cleanup_project,
        cleanup_inactive_deployments,
    ]
    redis_settings = RedisSettings.from_dsn("redis://redis:6379")
    max_jobs = 8
    job_timeout = settings.job_timeout
    job_completion_wait = settings.job_completion_wait
    health_check_interval = 65  # Greater than 60s to avoid health check timeout
    allow_abort_jobs = True
