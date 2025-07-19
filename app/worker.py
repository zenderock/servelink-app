from arq.connections import RedisSettings
from tasks.deploy import deploy
from tasks.cleanup import cleanup_project, cleanup_team, cleanup_inactive_deployments


class WorkerSettings:
    functions = [deploy, cleanup_project, cleanup_team, cleanup_inactive_deployments]
    redis_settings = RedisSettings.from_dsn("redis://redis:6379")
    max_jobs = 8
