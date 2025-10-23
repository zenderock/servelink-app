import asyncio
import logging
import aiodocker
from sqlalchemy import select, exc, inspect
from arq.connections import ArqRedis, RedisSettings, create_pool
import httpx
from datetime import datetime, timezone
from config import get_settings

from db import AsyncSessionLocal
from models import Deployment

logger = logging.getLogger(__name__)

deployment_probe_state = {}  # deployment_id -> {"container": container_obj, "probe_active": bool}


async def _http_probe(ip: str, port: int, timeout: float = 5) -> bool:
    """Check if the app responds to HTTP requests."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(f"http://{ip}:{port}/")
            return True
    except Exception:
        return False


async def _check_status(
    deployment: Deployment,
    docker_client: aiodocker.Docker,
    redis_pool: ArqRedis,
):
    """Checks the status of a single deployment's container."""
    if (
        deployment.id in deployment_probe_state
        and deployment_probe_state[deployment.id]["probe_active"]
    ):
        return

    log_prefix = f"[DeployMonitor:{deployment.id}]"

    # Timeout check
    try:
        settings = get_settings()
        now_utc = datetime.now(timezone.utc)
        created_at = (
            deployment.created_at.replace(tzinfo=timezone.utc)
            if deployment.created_at.tzinfo is None
            else deployment.created_at
        )
        if (now_utc - created_at).total_seconds() > settings.deployment_timeout:
            await redis_pool.enqueue_job(
                "deploy_fail", deployment.id, "Deployment timeout"
            )
            logger.warning(f"{log_prefix} Deployment timed out; failure job enqueued.")
            await _cleanup_deployment(deployment.id)
            return
    except Exception:
        logger.error(f"{log_prefix} Error while evaluating timeout.", exc_info=True)

    if deployment.id not in deployment_probe_state:
        try:
            container = await docker_client.containers.get(deployment.container_id)
            deployment_probe_state[deployment.id] = {
                "container": container,
                "probe_active": True,
            }
        except Exception:
            await redis_pool.enqueue_job(
                "deploy_fail", deployment.id, "Container not found"
            )
            return
    else:
        deployment_probe_state[deployment.id]["probe_active"] = True
        container = deployment_probe_state[deployment.id]["container"]

    # Probe check
    try:
        logger.info(f"{log_prefix} Probing container {deployment.container_id}")
        container_info = await container.show()
        status = container_info["State"]["Status"]

        if status == "exited":
            exit_code = container_info["State"].get("ExitCode", -1)
            reason = f"Container exited with code {exit_code}"
            await redis_pool.enqueue_job("deploy_fail", deployment.id, reason)
            logger.warning(
                f"{log_prefix} Deployment failed (failure job enqueued): {reason}"
            )
            await _cleanup_deployment(deployment.id)

        elif status == "running":
            networks = container_info.get("NetworkSettings", {}).get("Networks", {})
            container_ip = networks.get("servelink_runner", {}).get("IPAddress")
            if container_ip and await _http_probe(container_ip, 8000):
                await redis_pool.enqueue_job("deploy_finalize", deployment.id)
                logger.info(
                    f"{log_prefix} Deployment ready (finalization job enqueued)."
                )
                await _cleanup_deployment(deployment.id)

    except Exception as e:
        logger.error(
            f"{log_prefix} Unexpected error while checking status.", exc_info=True
        )
        await redis_pool.enqueue_job("deploy_fail", deployment.id, str(e))
        await _cleanup_deployment(deployment.id)
    finally:
        if deployment.id in deployment_probe_state:
            deployment_probe_state[deployment.id]["probe_active"] = False


# Cleanup function
async def _cleanup_deployment(deployment_id: str):
    """Cleans up a deployment from the status dictionary."""
    if deployment_id in deployment_probe_state:
        del deployment_probe_state[deployment_id]


async def monitor():
    """Monitors the status of deployments."""
    logger.info("Deployment monitor started")
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_pool = await create_pool(redis_settings)

    async with AsyncSessionLocal() as db:
        async with aiodocker.Docker(url=settings.docker_host) as docker_client:
            schema_ready = False
            while True:
                try:
                    # Ensure schema exists to avoid logging spam before migrations
                    if not schema_ready:
                        schema_ready = await db.run_sync(
                            lambda sync_session: inspect(
                                sync_session.connection()
                            ).has_table("alembic_version")
                        )
                        if not schema_ready:
                            logger.warning(
                                "Database schema not ready (no alembic_version); waiting for migrations..."
                            )
                            await asyncio.sleep(5)
                            continue

                    result = await db.execute(
                        select(Deployment).where(
                            Deployment.status == "in_progress",
                            Deployment.container_status == "running",
                        )
                    )
                    deployments_to_check = result.scalars().all()

                    if deployments_to_check:
                        tasks = [
                            _check_status(deployment, docker_client, redis_pool)
                            for deployment in deployments_to_check
                        ]
                        await asyncio.gather(*tasks)

                except exc.SQLAlchemyError as e:
                    logger.error(f"Database error in monitor loop: {e}. Reconnecting.")
                    await db.close()
                    db = AsyncSessionLocal()
                except Exception:
                    logger.error("Critical error in monitor main loop", exc_info=True)

                await asyncio.sleep(2)


if __name__ == "__main__":
    import asyncio

    asyncio.run(monitor())
