import os
import yaml
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from arq.connections import ArqRedis

from models import Deployment, Alias, Project, User
from utils.environment import get_environment_for_branch
from config import Settings

logger = logging.getLogger(__name__)


class DeploymentService:
    def __init__(self):
        pass

    async def update_traefik_config(
        self,
        project: Project,
        db: AsyncSession,
        settings: Settings,
    ) -> None:
        """Update Traefik config for a project."""

        path = os.path.join(settings.traefik_config_dir, f"project_{project.id}.yml")
        result = await db.execute(
            select(Alias)
            .join(Deployment, Alias.deployment_id == Deployment.id)
            .filter(
                Deployment.project_id == project.id,
                Deployment.conclusion == "succeeded",
            )
        )
        aliases = result.scalars().all()
        if not aliases and os.path.exists(path):
            os.remove(path)
        else:
            routers = {
                f"router-alias-{a.id}": {
                    "rule": f"Host(`{a.subdomain}.{settings.deploy_domain}`)",
                    "service": f"deployment-{a.deployment_id}@docker",
                }
                for a in aliases
            }
            os.makedirs(settings.traefik_config_dir, exist_ok=True)
            with open(path, "w") as f:
                yaml.dump({"http": {"routers": routers}}, f, sort_keys=False, indent=2)

    async def create_deployment(
        self,
        project: Project,
        branch: str,
        commit: dict,
        db: AsyncSession,
        redis_client: Redis,
        deployment_queue: ArqRedis,
        trigger: str = "user",
        current_user: User | None = None,
    ) -> Deployment:
        """Create a new deployment."""

        environment = get_environment_for_branch(branch, project.active_environments)
        if not environment:
            raise ValueError("No environment found for this branch.")

        deployment = Deployment(
            project=project,
            environment_id=environment.get("id", ""),
            branch=branch,
            commit_sha=commit["sha"],
            commit_meta={
                "author": commit["author"]["login"],
                "message": commit["commit"]["message"],
                "date": datetime.fromisoformat(
                    commit["commit"]["author"]["date"].replace("Z", "+00:00")
                ).isoformat(),
            },
            trigger=trigger,
            created_by_user_id=current_user.id
            if trigger == "user" and current_user
            else None,
        )
        db.add(deployment)
        await db.commit()

        await redis_client.xadd(
            f"stream:project:{project.id}:updates",
            fields={
                "event_type": "deployment_creation",
                "project_id": project.id,
                "deployment_id": deployment.id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        await deployment_queue.enqueue_job("deploy", deployment.id)
        logger.info(
            f"Deployment {deployment.id} created and queued for "
            f"project {project.name} ({project.id}) to environment {environment.get('name')} ({environment.get('id')})"
        )

        return deployment

    async def rollback(
        self,
        environment: dict,
        project: Project,
        db: AsyncSession,
        redis_client: Redis,
        settings: Settings,
    ) -> Alias:
        """Rollback an environment to its previous deployment."""
        subdomain = (
            project.slug
            if environment["id"] == "prod"
            else f"{project.slug}-env-{environment['slug']}"
        )

        alias = (
            await db.execute(select(Alias).where(Alias.subdomain == subdomain))
        ).scalar_one_or_none()

        if not alias or not alias.previous_deployment_id:
            raise ValueError("No previous deployment to roll back to.")

        alias.deployment_id, alias.previous_deployment_id = (
            alias.previous_deployment_id,
            alias.deployment_id,
        )
        await db.commit()

        await self.update_traefik_config(project, db, settings)

        await redis_client.xadd(
            f"stream:project:{project.id}:updates",
            fields={
                "event_type": "deployment_rollback",
                "environment_id": environment["id"],
                "deployment_id": alias.deployment_id,
                "previous_deployment_id": alias.previous_deployment_id or "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        return alias

    # async def promote(
    #     self,
    #     environment: dict,
    #     deployment: Deployment,
    #     project: Project,
    #     db: AsyncSession,
    #     redis_client: Redis,
    #     settings: Settings,
    # ) -> Alias:
    #     """Promote a deployment as current for an environment."""
    #     subdomain = (
    #         project.slug
    #         if environment["id"] == "prod"
    #         else f"{project.slug}-env-{environment['slug']}"
    #     )

    #     alias = (
    #         await db.execute(select(Alias).where(Alias.subdomain == subdomain))
    #     ).scalar_one_or_none()

    #     if not alias:
    #         raise ValueError("No alias found for this environment.")

    #     alias.deployment_id, alias.previous_deployment_id = (
    #         deployment.id,
    #         alias.deployment_id,
    #     )
    #     await db.commit()

    #     await self.update_traefik_config(project, db, settings)

    #     await redis_client.xadd(
    #         f"stream:project:{project.id}:updates",
    #         fields={
    #             "event_type": "deployment_promotion",
    #             "environment_id": environment["id"],
    #             "deployment_id": alias.deployment_id,
    #             "previous_deployment_id": alias.previous_deployment_id or "",
    #             "timestamp": datetime.now(timezone.utc).isoformat(),
    #         },
    #     )

    #     return alias
