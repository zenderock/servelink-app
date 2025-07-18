import re
import time
import asyncio
from datetime import datetime, timezone
import aiodocker
import httpx
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload
from typing import Any

from models import Deployment, Alias, Project
from dependencies import (
    get_redis_client,
    get_github_installation_service,
)
from config import get_settings
from arq.connections import ArqRedis
from services.deployment import DeploymentService

logger = logging.getLogger(__name__)


async def publish_docker_logs(container, offset, redis_client, stream_key):
    logs = await container.log(stdout=True, stderr=True, timestamps=True)
    updated_logs = "".join(logs)
    new_logs = updated_logs[offset:]

    parsed_new_logs = [
        {
            "timestamp": timestamp if separator else None,
            "message": message if separator else timestamp,
        }
        for timestamp, separator, message in (
            line.partition(" ") for line in new_logs.splitlines()
        )
    ]

    for log in parsed_new_logs:
        await redis_client.xadd(
            stream_key,
            {
                "event_type": "deployment_log",
                "timestamp": log.get(
                    "timestamp", datetime.now(timezone.utc).isoformat()
                ),
                "message": log.get("message", ""),
                "source": "build",
            },
        )
    return updated_logs


async def http_probe(ip, port, path="/", timeout=2):
    url = f"http://{ip}:{port}{path}"
    try:
        async with httpx.AsyncClient() as client:
            request = await client.get(url, timeout=timeout)
            return request.status_code < 500
    except httpx.RequestError:
        return False


async def deploy(ctx, deployment_id: str):
    """Deploy a project to its environment."""
    settings = get_settings()
    redis_client = get_redis_client()

    github_installation_service = get_github_installation_service()

    database_url = f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@pgsql:5432/{settings.postgres_db}"
    engine = create_async_engine(database_url, echo=settings.db_echo)
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSessionLocal() as db:
        try:
            deployment = (
                await db.execute(
                    select(Deployment)
                    .options(joinedload(Deployment.project))
                    .where(Deployment.id == deployment_id)
                )
            ).scalar_one()

            if not deployment:
                error_message = f"Deployment {deployment_id} not found"
                logger.error(error_message)
                raise Exception(error_message)

            project = await db.get(Project, deployment.project_id)
            if not project:
                error_message = f"Project {deployment.project_id} not found"
                logger.error(error_message)
                raise Exception(error_message)

            environment = project.get_environment_by_id(deployment.environment_id)
            if not environment:
                error_message = f"Environment {deployment.environment_id} not found"
                logger.error(error_message)
                raise Exception(error_message)

            # Check project status
            if project.status != "active":
                logger.warning(
                    f"Deployment {deployment_id} for project {project.id} ({project.name}) "
                    f"will not proceed as project status is '{project.status}'."
                )
                deployment.status = "skipped"
                deployment.conclusion = "skipped"
                deployment.build_logs = (
                    f"Skipped: Project status is '{project.status}'."
                )
                deployment.concluded_at = datetime.now(timezone.utc)
                await db.commit()
                return

            container = None
            container_logs = ""

            async with aiodocker.Docker(url=settings.docker_host) as docker_client:
                try:
                    # Mark deployment as in-progress
                    deployment.status = "in_progress"
                    await db.commit()

                    fields: Any = {
                        "event_type": "deployment_status_update",
                        "project_id": project.id,
                        "deployment_id": deployment.id,
                        "deployment_status": "in_progress",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    await redis_client.xadd(
                        f"stream:project:{project.id}:updates", fields
                    )
                    await redis_client.xadd(
                        f"stream:project:{project.id}:deployment:{deployment.id}:status",
                        fields,
                    )

                    # Prepare environment variables
                    env_vars_dict = {
                        var["key"]: var["value"] for var in (deployment.env_vars or [])
                    }
                    env_vars_dict["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

                    # Prepare commands
                    commands = []

                    # Step 1: Clone the repository
                    commands.append(
                        f"echo 'Cloning {deployment.repo_full_name} (Branch: {deployment.branch}, Commit: {deployment.commit_sha[:7]})'"
                    )
                    github_installation = (
                        await github_installation_service.get_or_refresh_installation(
                            project.github_installation_id, db
                        )
                    )
                    commands.append(
                        "git init -q && "
                        f"git fetch -q --depth 1 https://x-access-token:{github_installation.token}@github.com/{deployment.repo_full_name}.git {deployment.commit_sha} && "
                        f"git checkout -q FETCH_HEAD"
                    )

                    # Step 2: Install dependencies
                    commands.append("echo 'Installing dependencies...'")
                    commands.append(
                        deployment.config.get(
                            "build_command",
                            "pip install --progress-bar off -r requirements.txt",
                        )
                    )

                    # Step 3: Run pre-deploy command
                    if deployment.config.get("pre_deploy_command"):
                        commands.append("echo 'Running pre-deploy command...'")
                        commands.append(deployment.config.get("pre_deploy_command"))

                    # Step 4: Start the application
                    commands.append(
                        "(python -c 'import gunicorn' 2>/dev/null || "
                        "(echo 'Installing gunicorn...' && pip install --progress-bar off gunicorn))"
                    )
                    commands.append("echo 'Starting application...'")
                    commands.append(
                        deployment.config.get(
                            "start_command",
                            "gunicorn --log-level warning --bind 0.0.0.0:8000 main:app",
                        )
                    )

                    # Setup container configuration
                    container_name = f"runner-{deployment.id[:7]}"
                    router = f"deployment-{deployment.id}"

                    labels = {
                        "traefik.enable": "true",
                        f"traefik.http.routers.{router}.rule": f"Host(`{deployment.slug}.{settings.deploy_domain}`)",
                        f"traefik.http.routers.{router}.service": f"{router}@docker",
                        f"traefik.http.services.{router}.loadbalancer.server.port": "8000",
                        "traefik.docker.network": "devpush_default",
                        "app.deployment_id": deployment.id,
                        "app.project_id": project.id,
                    }

                    if settings.url_scheme == "https":
                        labels.update(
                            {
                                f"traefik.http.routers.{router}.entrypoints": "websecure",
                                f"traefik.http.routers.{router}.tls": "true",
                                f"traefik.http.routers.{router}.tls.certresolver": "le",
                            }
                        )
                    else:
                        labels[f"traefik.http.routers.{router}.entrypoints"] = "web"

                    # Create and start container
                    container = await docker_client.containers.create_or_replace(
                        name=container_name,
                        config={
                            "Image": "runner",
                            "Cmd": ["/bin/sh", "-c", " && ".join(commands)],
                            "Env": [f"{k}={v}" for k, v in env_vars_dict.items()],
                            "WorkingDir": "/app",
                            "Labels": labels,
                            "NetworkingConfig": {
                                "EndpointsConfig": {"devpush_default": {}}
                            },
                        },
                    )

                    await container.start()

                    # Connect to internal network
                    internal_network = await docker_client.networks.get(
                        "devpush_internal"
                    )
                    await internal_network.connect({"Container": container.id})

                    # Save container info
                    deployment.container_id = container.id
                    deployment.container_status = "running"
                    await db.commit()

                    # Wait for deployment to complete
                    start_time = time.time()
                    timeout = settings.deployment_timeout

                    while (time.time() - start_time) < timeout:
                        container_info = await container.show()

                        if container_info["State"]["Status"] == "exited":
                            raise Exception("Container failed to start")

                        # Publish logs
                        container_logs = await publish_docker_logs(
                            container,
                            len(container_logs),
                            redis_client,
                            f"stream:project:{project.id}:deployment:{deployment.id}:logs",
                        )

                        # Check if app is ready
                        networks = container_info.get("NetworkSettings", {}).get(
                            "Networks", {}
                        )
                        container_ip = networks.get("devpush_default", {}).get(
                            "IPAddress"
                        )

                        if not container_ip:
                            logger.info(
                                f"Container {container.id} not yet assigned an IP address"
                            )
                            await asyncio.sleep(0.5)
                            continue

                        if await http_probe(container_ip, 8000):
                            deployment.conclusion = "succeeded"
                            break

                        await asyncio.sleep(0.5)
                    else:
                        raise Exception("Timeout waiting for application to start")

                    # Setup branch domains
                    branch = (
                        deployment.branch
                    )  # Won't prevent collisions, but good enough
                    sanitized_branch = re.sub(r"[^a-zA-Z0-9-]", "-", branch)
                    branch_subdomain = f"{project.slug}-branch-{sanitized_branch}"

                    try:
                        await Alias.update_or_create(
                            db,
                            subdomain=branch_subdomain,
                            deployment_id=deployment.id,
                            type="branch",
                            value=branch,
                        )
                    except Exception as e:
                        logger.error(f"Failed to setup branch alias: {e}")

                    # Environment alias
                    if deployment.environment_id == "prod":
                        env_subdomain = project.slug
                    else:
                        env_subdomain = f"{project.slug}-env-{environment.get('slug')}"

                    try:
                        await Alias.update_or_create(
                            db,
                            subdomain=env_subdomain,
                            deployment_id=deployment.id,
                            type="environment",
                            value=deployment.environment_id,
                        )
                    except Exception as e:
                        logger.error(f"Failed to setup environment alias: {e}")

                    await db.commit()

                    # Update Traefik dynamic config
                    await DeploymentService().update_traefik_config(
                        project, db, settings
                    )

                    # Cleanup inactive deployments
                    deployment_queue: ArqRedis = ctx["redis"]
                    await deployment_queue.enqueue_job(
                        "cleanup_inactive_deployments", project.id
                    )
                    logger.info(
                        f"Inactive deployments cleanup job queued for project {project.id}."
                    )

                    # Success message
                    success_message = f"Deployment succeeded. Visit {deployment.url}"
                    await container.exec(
                        ["/bin/sh", "-c", f"echo '{success_message}' >> /proc/1/fd/1"]
                    )

                except Exception as e:
                    await db.rollback()
                    deployment.conclusion = "failed"
                    if deployment.container_status:
                        deployment.container_status = "stopped"
                    logger.error(
                        f"Deployment {deployment_id} failed: {e}", exc_info=True
                    )

                finally:
                    # Update deployment status
                    project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    deployment.status = "completed"
                    deployment.concluded_at = datetime.now(timezone.utc).replace(
                        tzinfo=None
                    )

                    if container:
                        container_logs = await publish_docker_logs(
                            container,
                            len(container_logs),
                            redis_client,
                            f"stream:project:{project.id}:deployment:{deployment.id}:logs",
                        )

                    deployment.build_logs = container_logs
                    await db.commit()

                    fields = {
                        "event_type": "deployment_status_update",
                        "project_id": project.id,
                        "deployment_id": deployment.id,
                        "deployment_status": deployment.conclusion,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    await redis_client.xadd(
                        f"stream:project:{project.id}:deployment:{deployment.id}:status",
                        fields,
                    )
                    await redis_client.xadd(
                        f"stream:project:{project.id}:updates", fields
                    )

                    # Cleanup failed containers
                    if container and deployment.conclusion == "failed":
                        try:
                            await container.kill()
                            await container.delete(force=True)
                            deployment.container_status = "removed"
                            await db.commit()
                            logger.info(
                                f"Cleaned up failed container {container.id} from deployment {deployment.id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Error cleaning up container {container.id} from deployment {deployment.id}: {e}"
                            )

                    logger.info(
                        f"Deployment {deployment.id} completed with conclusion: {deployment.conclusion}"
                    )

        except Exception as e:
            await db.rollback()
            logger.error(f"Deploy task failed: {e}", exc_info=True)
            raise
