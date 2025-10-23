import logging
from arq.connections import RedisSettings
from arq import CronJob
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
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 8
    job_timeout = settings.job_timeout
    job_completion_wait = settings.job_completion_wait
    health_check_interval = 65  # Greater than 60s to avoid health check timeout
    allow_abort_jobs = True
    cron_jobs = [
        # Exécuter la vérification des projets inactifs tous les jours à 03h00 UTC
        CronJob(
            function=check_inactive_projects,
            cron="0 3 * * *",  # Tous les jours à 03h00 UTC
        )
    ]
