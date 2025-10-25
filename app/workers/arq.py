import logging
from arq.connections import RedisSettings
from arq.cron import cron
from workers.tasks.deploy import deploy_start, deploy_finalize, deploy_fail
from workers.tasks.cleanup import (
    cleanup_user,
    cleanup_team,
    cleanup_project,
    cleanup_inactive_deployments,
)
from workers.tasks.project_monitoring import (
    check_inactive_projects,
    reactivate_project_task,
)
from workers.tasks.usage_monitoring import (
    update_project_storage,
    check_usage_limits_task,
    expire_additional_resources,
)

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class WorkerSettings:
    functions = [
        deploy_start,
        deploy_finalize,
        deploy_fail,
        cleanup_user,
        cleanup_team,
        cleanup_project,
        cleanup_inactive_deployments,
        check_inactive_projects,
        reactivate_project_task,
        update_project_storage,
        check_usage_limits_task,
        expire_additional_resources,
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 8
    job_timeout = settings.job_timeout
    job_completion_wait = settings.job_completion_wait
    health_check_interval = 65  # Greater than 60s to avoid health check timeout
    allow_abort_jobs = True
    cron_jobs = [
        cron(check_inactive_projects, hour=2, minute=0, run_at_startup=False),
        cron(cleanup_inactive_deployments, hour=3, minute=0, run_at_startup=False),
        cron(update_project_storage, hour=4, minute=0, run_at_startup=False),
        cron(expire_additional_resources, hour=5, minute=0, run_at_startup=False),
        cron(check_usage_limits_task, hour=6, minute=0, run_at_startup=False),
    ]
