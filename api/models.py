from __future__ import annotations
from sqlalchemy import (
    BigInteger,
    JSON,
    String,
    Text,
    ForeignKey,
    Enum as SQLAEnum,
    DateTime,
    event,
    select,
    update,
    Boolean,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import json
from secrets import token_hex
from cryptography.fernet import Fernet
from functools import lru_cache
import re
from typing import override

from db import Base
from config import get_settings
from utils.colors import get_project_color


def utc_now() -> datetime:
    """Get current UTC time as timezone-naive datetime"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@lru_cache
def get_fernet() -> Fernet:
    """Get Fernet instance using encryption key from settings"""
    settings = get_settings()
    return Fernet(settings.encryption_key)


class User(Base):
    __tablename__: str = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(index=True, unique=True)
    email: Mapped[str] = mapped_column(String(320), index=True, unique=True)
    username: Mapped[str] = mapped_column(String(50), index=True, unique=True)
    name: Mapped[str] = mapped_column(String(256), index=True, nullable=True)
    _github_token: Mapped[str | None] = mapped_column("github_token", String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now, onupdate=utc_now
    )
    
    # Relationships
    projects: Mapped[list["Project"]] = relationship(back_populates="user")

    @override
    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def avatar(self):
        return f"https://unavatar.io/{self.email.lower()}"

    @property
    def github_token(self) -> str | None:
        if self._github_token:
            fernet = get_fernet()
            return fernet.decrypt(self._github_token.encode()).decode()
        return None

    @github_token.setter
    def github_token(self, value: str):
        if value:
            fernet = get_fernet()
            self._github_token = fernet.encrypt(value.encode()).decode()
        else:
            self._github_token = None


class Team(Base):
    __tablename__: str = "team"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now, onupdate=utc_now
    )


class GithubInstallation(Base):
    __tablename__: str = "github_installation"

    installation_id: Mapped[int] = mapped_column(primary_key=True)
    _token: Mapped[str | None] = mapped_column("token", String(2048), nullable=True)
    token_expires_at: Mapped[datetime] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        SQLAEnum("active", "deleted", "suspended", name="github_installation_status"),
        nullable=False,
        default="active",
    )

    # Relationships
    projects: Mapped[list["Project"]] = relationship(
        back_populates="github_installation"
    )

    @property
    def token(self) -> str | None:
        if self._token is None:
            return None
        fernet = get_fernet()
        return fernet.decrypt(self._token.encode()).decode()

    @token.setter
    def token(self, value: str):
        if not value:
            self._token = None
        else:
            fernet = get_fernet()
            self._token = fernet.encrypt(value.encode()).decode()

    @override
    def __repr__(self):
        return f"<GithubInstallation {self.installation_id}>"


class Project(Base):
    __tablename__: str = "project"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: token_hex(16)
    )
    name: Mapped[str] = mapped_column(String(100), index=True)
    has_avatar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repo_status: Mapped[str] = mapped_column(
        SQLAEnum(
            "active", "deleted", "removed", "transferred", name="project_github_status"
        ),
        nullable=False,
        default="active",
    )
    github_installation_id: Mapped[int] = mapped_column(
        ForeignKey("github_installation.installation_id"), nullable=False, index=True
    )
    environments: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    _env_vars: Mapped[str] = mapped_column("env_vars", Text, nullable=False, default="")
    slug: Mapped[str] = mapped_column(String(40), nullable=True, unique=True)
    config: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now, onupdate=utc_now
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    status: Mapped[str] = mapped_column(
        SQLAEnum("active", "paused", "deleted", name="project_status"),
        nullable=False,
        default="active",
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="projects")
    github_installation: Mapped[GithubInstallation] = relationship(
        back_populates="projects"
    )
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="project")

    @property
    def env_vars(self) -> list[dict[str, str]]:
        if self._env_vars:
            fernet = get_fernet()
            decrypted = fernet.decrypt(self._env_vars.encode()).decode()
            return json.loads(decrypted)
        return []

    @env_vars.setter
    def env_vars(self, value: list[dict[str, str]]):
        json_str = json.dumps(value or [])
        fernet = get_fernet()
        self._env_vars = fernet.encrypt(json_str.encode()).decode()

    @property
    def hostname(self) -> str:
        settings = get_settings()
        base_domain = getattr(settings, "apps_base_domain", settings.base_domain)
        return f"{self.slug}.{base_domain}"

    @property
    def url(self) -> str:
        settings = get_settings()
        return f"{settings.url_scheme}://{self.hostname}"

    # @property
    # async def aliases(self) -> list[str]:
    #     promoted_deployment = await self.promoted_deployment
    #     if promoted_deployment:
    #         return [alias.subdomain for alias in promoted_deployment.aliases]
    #     return []

    # @property
    # async def promoted_deployment(self) -> Deployment | None:
    #     # TODO: add a flag for promoted deployment (rollback)
    #     deployment = await db.scalar(
    #         select(Deployment)
    #         .where(
    #             Deployment.project_id == self.id,
    #             Deployment.conclusion == 'succeeded',
    #             # Deployment.environment == 'production'
    #         )
    #         .order_by(Deployment.created_at.desc())
    #         .limit(1)
    #     )
    #     return deployment

    @property
    def color(self) -> str:
        return get_project_color(self.id)

    @override
    def __repr__(self):
        return f"<Project {self.name}>"

    def get_config(self) -> dict[str, object]:
        """Get complete project configuration with framework defaults."""
        settings = get_settings()
        framework_slug = self.config.get("framework", "python")
        framework = next(
            (f for f in settings.frameworks if f.get("slug") == framework_slug), {}
        )

        return {
            "framework": framework,
            "build_command": self.config.get("build_command")
            or framework.get("build_command"),
            "pre_deploy_command": self.config.get("pre_deploy_command")
            or framework.get("pre_deploy_command"),
            "start_command": self.config.get("start_command")
            or framework.get("start_command"),
            "root_directory": self.config.get("root_directory")
            or framework.get("root_directory", "./"),
        }

    def get_env_vars(self, environment: str) -> list[dict[str, str]]:
        """Flattened env vars for a specific environment."""
        env_vars = [var for var in self.env_vars if not var.get("environment")]
        for var in self.env_vars:
            if var.get("environment") == environment:
                env_vars = [v for v in env_vars if v["key"] != var["key"]]
                env_vars.append(var)
        return env_vars

    def has_active_environment_with_slug(
        self, slug: str, exclude_id: str | None = None
    ) -> bool:
        """Check if an active environment with given slug exists"""
        return any(
            environment
            for environment in self.active_environments
            if environment.get("slug") == slug and (exclude_id is None or environment.get("id") != exclude_id)
        )

    def create_environment(self, name: str, slug: str, **kwargs) -> dict:
        """Create a new environment with a unique ID"""
        if self.has_active_environment_with_slug(slug):
            raise ValueError(f"An active environment with slug '{slug}' already exists")

        env = {
            "id": token_hex(4),
            "name": name,
            "slug": slug,
            "status": "active",
            **kwargs,
        }
        environments = self.environments.copy()
        environments.append(env)
        self.environments = environments
        return env

    def update_environment(self, environment_id: str, values: dict) -> dict | None:
        """Update environment"""
        env = self.get_environment_by_id(environment_id)
        if not env:
            return None

        # Prevent production rename
        if environment_id == "prod" and (env.get("name") != values.get("name") or env.get("slug") != values.get("slug")):
            raise ValueError("Cannot modify production environment")

        # If changing slug, check it's unique
        new_slug = values.get("slug")
        if (
            new_slug
            and new_slug != env.get("slug")
            and self.has_active_environment_with_slug(
                new_slug, exclude_id=environment_id
            )
        ):
            raise ValueError(
                f"An active environment with slug '{new_slug}' already exists"
            )

        # Update the environment
        env_index = next(
            i for i, e in enumerate(self.environments) if e["id"] == environment_id
        )
        old_slug = self.environments[env_index]["slug"]

        environments = self.environments.copy()
        environments[env_index] = {**environments[env_index], **values}
        self.environments = environments

        # Update env vars if slug changed
        if new_slug and new_slug != old_slug:
            env_vars = self.env_vars.copy()
            for var in env_vars:
                if var.get("environment") == old_slug:
                    var["environment"] = new_slug
            self.env_vars = env_vars

        return environments[env_index]

    def delete_environment(self, environment_id: str | None) -> bool:
        """Soft delete environment"""
        if not environment_id:
            return False

        if environment_id == "prod":
            raise ValueError("Cannot delete production environment")

        env = self.get_environment_by_id(environment_id)
        if not env:
            return False

        # Remove env vars for this environment
        env_vars = self.env_vars.copy()
        env_vars = [var for var in env_vars if var.get("environment") != env["slug"]]
        self.env_vars = env_vars

        # Mark environment as deleted
        env_index = next(
            i for i, e in enumerate(self.environments) if e["id"] == environment_id
        )
        environments = self.environments.copy()
        environments[env_index] = {**environments[env_index], "status": "deleted"}
        self.environments = environments
        return True

    @property
    def active_environments(self) -> list[dict]:
        """Get only active environments"""
        return [env for env in self.environments if env.get("status") == "active"]

    def get_environment_by_id(self, env_id: str) -> dict | None:
        """Get environment by ID"""
        return next((env for env in self.environments if env["id"] == env_id), None)

    def get_environment_by_slug(
        self, slug: str, active_only: bool = True
    ) -> dict | None:
        """Get environment by slug"""
        environments = self.active_environments if active_only else self.environments
        return next((env for env in environments if env["slug"] == slug), None)

    async def get_environment_aliases(self, db) -> dict[str, "Alias"]:
        """Get environment aliases for this project"""
        result = await db.execute(
            select(Alias)
            .join(Deployment, Alias.deployment_id == Deployment.id)
            .where(Deployment.project_id == self.id, Alias.type == "environment")
        )
        aliases = result.scalars().all()
        return {alias.value: alias for alias in aliases}


@event.listens_for(Project, "after_insert")
def set_project_slug(mapper, connection, project):
    """Generate and set slug after project is inserted (and has an ID)."""
    if not project.slug:
        # Convert to lowercase and replace dots/underscores with hyphens
        base_slug = (
            f"{project.name}-{project.user.username}".lower()
            .replace(".", "-")
            .replace("_", "-")
        )
        base_slug = re.sub(r"-+", "-", base_slug)
        base_slug = base_slug[:40]
        base_slug = base_slug.strip("-")

        # Try base slug first, if exists use ID version
        new_slug = (
            base_slug
            if not connection.scalar(
                select(Project.slug).where(Project.slug == base_slug)
            )
            else f"{base_slug[:32]}-{str(project.id)[:7]}"
        )

        # Update both database and instance
        connection.execute(
            update(Project).where(Project.id == project.id).values(slug=new_slug)
        )
        project.slug = new_slug


class Deployment(Base):
    __tablename__: str = "deployment"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: token_hex(16)
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    environment_id: Mapped[str] = mapped_column(String(8), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), index=True)
    commit_sha: Mapped[str] = mapped_column(String(40), index=True)
    commit_meta: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    config: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    _env_vars: Mapped[str] = mapped_column("env_vars", Text, nullable=False, default="")
    container_id: Mapped[str] = mapped_column(String(64), nullable=True)
    container_status: Mapped[str] = mapped_column(
        SQLAEnum("running", "stopped", "removed", name="deployment_container_status"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        SQLAEnum("queued", "in_progress", "completed", name="deployment_status"),
        nullable=False,
        default="queued",
    )
    conclusion: Mapped[str] = mapped_column(
        SQLAEnum(
            "succeeded", "failed", "canceled", "skipped", name="deployment_conclusion"
        ),
        nullable=True,
    )
    trigger: Mapped[str] = mapped_column(
        SQLAEnum("webhook", "user", "api", name="deployment_trigger"),
        nullable=False,
        default="user",
    )
    created_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now
    )
    concluded_at: Mapped[datetime] = mapped_column(index=True, nullable=True)
    build_logs: Mapped[str] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped[Project] = relationship(back_populates="deployments")
    aliases: Mapped[list["Alias"]] = relationship(
        back_populates="deployment", foreign_keys="Alias.deployment_id"
    )

    def __init__(self, *, project: "Project", environment_id: str, **kwargs):
        super().__init__(project=project, environment_id=environment_id, **kwargs)
        # Snapshot repo, config, environments and env_vars from project at time of creation
        self.repo_id = project.repo_id
        self.repo_full_name = project.repo_full_name
        self.config = project.get_config()
        environment = project.get_environment_by_id(environment_id)
        self.env_vars = project.get_env_vars(environment["slug"]) if environment else []

    @property
    def environment(self) -> dict | None:
        """Get environment configuration"""
        return self.project.get_environment_by_id(self.environment_id)

    @property
    def env_vars(self) -> list[dict[str, str]]:
        if self._env_vars:
            fernet = get_fernet()
            decrypted = fernet.decrypt(self._env_vars.encode()).decode()
            return json.loads(decrypted)
        return []

    @env_vars.setter
    def env_vars(self, value: list[dict[str, str]] | None):
        json_str = json.dumps(value or [])
        fernet = get_fernet()
        self._env_vars = fernet.encrypt(json_str.encode()).decode()

    @property
    def slug(self) -> str:
        return f"{self.project.slug}-id-{self.id[:7]}"

    @property
    def hostname(self) -> str:
        settings = get_settings()
        base_domain = getattr(settings, "apps_base_domain", settings.base_domain)
        return f"{self.slug}.{base_domain}"

    @property
    def url(self) -> str:
        settings = get_settings()
        return f"{settings.url_scheme}://{self.hostname}"

    @property
    def featured_slug(self) -> str | None:
        if not self.conclusion:
            return None
        env_alias = next((a for a in self.aliases if a.type == "environment"), None)
        if env_alias:
            return env_alias.subdomain
        branch_alias = next((a for a in self.aliases if a.type == "branch"), None)
        if branch_alias:
            return branch_alias.subdomain
        return self.slug

    @property
    def featured_hostname(self) -> str | None:
        if not self.conclusion:
            return None
        settings = get_settings()
        base_domain = getattr(settings, "apps_base_domain", settings.base_domain)
        return f"{self.featured_slug}.{base_domain}"

    @property
    def featured_url(self) -> str | None:
        if not self.conclusion:
            return None
        settings = get_settings()
        return f"{settings.url_scheme}://{self.featured_hostname}"

    def __repr__(self):
        return f"<Deployment {self.id}>"

    def parse_logs(self):
        """Parse raw build logs into structured format."""
        if not self.build_logs:
            return []

        logs = [
            {
                "timestamp": timestamp if separator else None,
                "message": message if separator else timestamp,
            }
            for timestamp, separator, message in (
                line.partition(" ") for line in self.build_logs.splitlines()
            )
        ]
        return logs

    @property
    def parsed_logs(self):
        return self.parse_logs()


class Alias(Base):
    __tablename__: str = "alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    subdomain: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployment.id"), index=True)
    previous_deployment_id: Mapped[str] = mapped_column(
        ForeignKey("deployment.id"), index=True, nullable=True
    )
    type: Mapped[str] = mapped_column(
        SQLAEnum("branch", "environment", name="alias_type"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        index=True, nullable=False, default=utc_now, onupdate=utc_now
    )

    # Relationships
    deployment: Mapped[Deployment] = relationship(
        foreign_keys=[deployment_id], back_populates="aliases"
    )
    previous_deployment: Mapped[Deployment] = relationship(
        foreign_keys=[previous_deployment_id]
    )

    @property
    def hostname(self) -> str:
        settings = get_settings()
        base_domain = getattr(settings, "apps_base_domain", settings.base_domain)
        return f"{self.subdomain}.{base_domain}"

    @property
    def url(self) -> str:
        settings = get_settings()
        return f"{settings.url_scheme}://{self.hostname}"

    @classmethod
    async def update_or_create(
        cls,
        db: AsyncSession,
        subdomain: str,
        deployment_id: str,
        type: str,
        value: str | None = None,
    ) -> dict[str, object]:
        """Update or create alias"""
        result_query = await db.execute(select(cls).where(cls.subdomain == subdomain))
        alias = result_query.scalar_one_or_none()

        result = {}
        result["alias"] = None
        result["demoted_previous_deployment_id"] = None

        if alias:
            if alias.deployment_id == deployment_id:
                result["alias"] = alias
                return result

            result["demoted_previous_deployment_id"] = alias.previous_deployment_id
            alias.previous_deployment_id = alias.deployment_id
            alias.deployment_id = deployment_id
        else:
            alias = cls(
                subdomain=subdomain,
                deployment_id=deployment_id,
                type=type,
                value=value,
            )
            db.add(alias)

        result["alias"] = alias
        return result

    @override
    def __repr__(self):
        return f"<Alias {self.subdomain}>"
