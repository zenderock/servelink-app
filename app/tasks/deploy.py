import re
import time
import asyncio
from datetime import datetime, timezone
import aiodocker
import logging
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from typing import Any
import socket
import httpx

from models import Deployment, Alias, Project
from db import AsyncSessionLocal
from dependencies import (
    get_redis_client,
    get_github_installation_service,
)
from config import get_settings
from arq.connections import ArqRedis
from services.deployment import DeploymentService

logger = logging.getLogger(__name__)


async def _log_to_container(container, message, error=False):
    fd = "2" if error else "1"
    exec = await container.exec(
        ["/bin/sh", "-c", f"echo '{message}' >> /proc/1/fd/{fd}"],
        user="appuser",
        stdout=False,
        stderr=False,
    )
    await exec.start(detach=True)


async def _tcp_probe(ip: str, port: int, timeout: float = 5) -> bool:
    """Return True as soon as a TCP connection can be made."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: socket.create_connection((ip, port), timeout).close(),
        )
        return True
    except OSError:
        return False


async def _http_probe(ip: str, port: int, timeout: float = 5) -> bool:
    """Check if the app responds to HTTP requests."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"http://{ip}:{port}/")
            return response.status_code < 500  # Accept 2xx, 3xx, 4xx
    except Exception:
        return False


async def deploy(ctx, deployment_id: str):
    """Deploy a project to its environment."""
    try:
        settings = get_settings()
        redis_client = get_redis_client()
        log_prefix = f"[Deploy:{deployment_id}]"
        logger.info(f"{log_prefix} Starting deployment")

        github_installation_service = get_github_installation_service()

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
                    error_message = "Deployment not found"
                    logger.error(f"{log_prefix} {error_message}")
                    raise Exception(f"{log_prefix} {error_message}")

                project = await db.get(Project, deployment.project_id)
                if not project:
                    error_message = f"Project {deployment.project_id} not found"
                    logger.error(f"{log_prefix} {error_message}")
                    raise Exception(f"{log_prefix} {error_message}")

                environment = project.get_environment_by_id(deployment.environment_id)
                if not environment:
                    error_message = f"Environment {deployment.environment_id} not found"
                    logger.error(f"{log_prefix} {error_message}")
                    raise Exception(f"{log_prefix} {error_message}")

                # Check project status
                if project.status != "active":
                    logger.warning(
                        f"{log_prefix} Project {project.id} has a status of '{project.status}'."
                    )
                    deployment.status = "skipped"
                    deployment.conclusion = "skipped"
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
                            var["key"]: var["value"]
                            for var in (deployment.env_vars or [])
                        }
                        # env_vars_dict["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

                        # Prepare commands
                        commands = []

                        # Step 1: Clone the repository
                        commands.append(
                            f"echo 'Cloning {deployment.repo_full_name} (Branch: {deployment.branch}, Commit: {deployment.commit_sha[:7]})'"
                        )
                        github_installation = await github_installation_service.get_or_refresh_installation(
                            project.github_installation_id, db
                        )
                        commands.append(
                            "git init -q && "
                            f"git fetch -q --depth 1 https://x-access-token:{github_installation.token}@github.com/{deployment.repo_full_name}.git {deployment.commit_sha} && "
                            f"git checkout -q FETCH_HEAD"
                        )

                        # Step 2: Install dependencies
                        if deployment.config.get("build_command"):
                            commands.append("echo 'Installing dependencies...'")
                            commands.append(deployment.config.get("build_command"))

                        # Step 3: Run pre-deploy command
                        if deployment.config.get("pre_deploy_command"):
                            commands.append("echo 'Running pre-deploy command...'")
                            commands.append(deployment.config.get("pre_deploy_command"))

                        # Step 4: Start the application
                        commands.append("echo 'Starting application...'")
                        commands.append(deployment.config.get("start_command"))

                        # Setup container configuration
                        container_name = f"runner-{deployment.id[:7]}"
                        router = f"deployment-{deployment.id}"

                        labels = {
                            "traefik.enable": "true",
                            f"traefik.http.routers.{router}.rule": f"Host(`{deployment.slug}.{settings.deploy_domain}`)",
                            f"traefik.http.routers.{router}.service": f"{router}@docker",
                            f"traefik.http.routers.{router}.priority": "10",
                            f"traefik.http.services.{router}.loadbalancer.server.port": "8000",
                            "traefik.docker.network": "devpush_runner",
                            "deployment_id": deployment.id,
                            "project_id": project.id,
                            "environment_id": deployment.environment_id,
                            "branch": deployment.branch,
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

                        # Get resource limits from config
                        try:
                            cpu_quota = int(
                                deployment.config.get("cpu")
                                or settings.default_cpu_quota
                            )
                            memory_mb = int(
                                deployment.config.get("memory")
                                or settings.default_memory_mb
                            )
                        except (ValueError, TypeError):
                            cpu_quota = settings.default_cpu_quota
                            memory_mb = settings.default_memory_mb
                            logger.warning(
                                f"{log_prefix} Invalid CPU/memory values in config, using defaults."
                            )

                        runtime = project.config.get("runtime")

                        # Create and start container
                        container = await docker_client.containers.create_or_replace(
                            name=container_name,
                            config={
                                "Image": f"runner-{runtime}",
                                "Cmd": ["/bin/sh", "-c", " && ".join(commands)],
                                "Env": [f"{k}={v}" for k, v in env_vars_dict.items()],
                                "WorkingDir": "/app",
                                "Labels": labels,
                                "NetworkingConfig": {
                                    "EndpointsConfig": {"devpush_runner": {}}
                                },
                                "HostConfig": {
                                    "CpuQuota": cpu_quota,
                                    "Memory": memory_mb * 1024 * 1024,
                                    "CapDrop": ["ALL"],
                                    "SecurityOpt": ["no-new-privileges:true"],
                                    "LogConfig": {
                                        "Type": "loki",
                                        "Config": {
                                            "loki-url": "http://127.0.0.1:3100/loki/api/v1/push",
                                            "loki-batch-size": "200",
                                            "labels": "deployment_id,project_id,environment_id,branch",
                                        },
                                    },
                                },
                            },
                        )

                        await container.start()

                        # Save container info
                        deployment.container_id = container.id
                        deployment.container_status = "running"
                        await db.commit()

                        # Wait for deployment to complete
                        start_time = time.time()

                        while (time.time() - start_time) < settings.deployment_timeout:
                            container_info = await container.show()
                            logger.info(
                                f"{log_prefix} Container status: {container_info['State']['Status']}"
                            )

                            if container_info["State"]["Status"] == "exited":
                                exit_code = container_info["State"].get("ExitCode", -1)
                                raise Exception(
                                    f"Container exited with code {exit_code}"
                                )

                            # Check if app is ready
                            networks = container_info.get("NetworkSettings", {}).get(
                                "Networks", {}
                            )
                            container_ip = networks.get("devpush_runner", {}).get(
                                "IPAddress"
                            )

                            if not container_ip:
                                logger.info(
                                    f"{log_prefix} Container {container.id} not yet assigned an IP address"
                                )
                                await asyncio.sleep(0.5)
                                continue

                            if await _http_probe(container_ip, 8000):
                                deployment.conclusion = "succeeded"
                                break

                            await asyncio.sleep(0.5)
                        else:
                            await _log_to_container(
                                container,
                                "Timeout waiting for application to reply on port 8000.",
                                error=True,
                            )
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
                            await _log_to_container(
                                container,
                                f"Assigned branch alias ({branch_subdomain}.{settings.deploy_domain})",
                            )
                        except Exception as e:
                            await _log_to_container(
                                container,
                                f"Warning: Failed to setup branch alias ({branch_subdomain}.{settings.deploy_domain})",
                                error=True,
                            )
                            logger.warning(
                                f"{log_prefix} Failed to setup branch alias: {e}"
                            )

                        # Environment alias
                        if deployment.environment_id == "prod":
                            env_subdomain = project.slug
                        else:
                            env_subdomain = (
                                f"{project.slug}-env-{environment.get('slug')}"
                            )

                        try:
                            await Alias.update_or_create(
                                db,
                                subdomain=env_subdomain,
                                deployment_id=deployment.id,
                                type="environment",
                                value=deployment.environment_id,
                                environment_id=deployment.environment_id,
                            )
                            await _log_to_container(
                                container,
                                f"Assigned environment alias ({env_subdomain}.{settings.deploy_domain})",
                            )
                        except Exception as e:
                            await _log_to_container(
                                container,
                                f"Warning: Failed to setup environment alias ({env_subdomain}.{settings.deploy_domain})",
                                error=True,
                            )
                            logger.error(
                                f"{log_prefix} Failed to setup environment alias: {e}"
                            )

                        await db.commit()

                        # Success message
                        await _log_to_container(
                            container,
                            f"Success: Deployment is available at {deployment.url}",
                        )

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
                            f"{log_prefix} Inactive deployments cleanup job queued for project {project.id}."
                        )

                    except Exception as e:
                        await db.rollback()
                        deployment.conclusion = "failed"
                        if deployment.container_status:
                            deployment.container_status = "stopped"
                        logger.error(
                            f"{log_prefix} Deployment failed: {e}", exc_info=True
                        )

                    finally:
                        logger.info(
                            f"{log_prefix} FINAL CONTAINER LOGS: {container_logs}"
                        )

                        if not deployment.conclusion:
                            deployment.conclusion = "succeeded"

                        # Update deployment status
                        project.updated_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
                        deployment.status = "completed"
                        deployment.concluded_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
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
                                    f"{log_prefix} Cleaned up failed container {container.id}"
                                )
                            except Exception as e:
                                logger.error(
                                    f"{log_prefix} Error cleaning up container {container.id}: {e}"
                                )

                        logger.info(
                            f"{log_prefix} Deployment completed with conclusion: {deployment.conclusion}"
                        )

            except Exception as e:
                await db.rollback()
                logger.error(
                    f"[Deploy:{deployment_id}] Deploy task failed: {e}", exc_info=True
                )
                raise

    except asyncio.CancelledError:
        log_prefix = f"[Deploy:{deployment_id}]"
        logger.info(f"{log_prefix} Deployment canceled")

        if container:
            try:
                await container.kill()
                await container.delete(force=True)
            except Exception as e:
                logger.error(f"{log_prefix} Error cleaning up container: {e}")

        try:
            async with AsyncSessionLocal() as db:
                deployment = await db.get(Deployment, deployment_id)
                if deployment:
                    deployment.conclusion = "canceled"
                    deployment.concluded_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception as e:
            logger.error(f"{log_prefix} Error updating deployment status: {e}")

        raise
