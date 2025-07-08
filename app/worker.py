from arq.connections import RedisSettings
from tasks.deploy import deploy

class WorkerSettings:
    functions = [deploy]
    redis_settings = RedisSettings.from_dsn("redis://redis:6379") 