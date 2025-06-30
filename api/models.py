from __future__ import annotations
from sqlalchemy import BigInteger, JSON, String, Text, ForeignKey, Enum as SQLAEnum, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import json
from secrets import token_hex
from cryptography.fernet import Fernet
from functools import lru_cache
from db import Base
from config import get_settings


@lru_cache
def get_fernet() -> Fernet:
    """Get Fernet instance using encryption key from settings"""
    settings = get_settings()
    return Fernet(settings.encryption_key)


class User(Base):
    __tablename__ = 'user'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(index=True, unique=True)
    email: Mapped[str] = mapped_column(String(320), index=True, unique=True)
    username: Mapped[str] = mapped_column(String(50), index=True, unique=True)
    name: Mapped[str] = mapped_column(String(256), index=True, nullable=True)
    _github_token: Mapped[str] = mapped_column('github_token', String(2048), nullable=True)
    
    projects: Mapped[list['Project']] = relationship(back_populates='user')

    def __repr__(self):
        return f'<User {self.email}>'

    @property
    def avatar(self):
        return f'https://unavatar.io/{self.email.lower()}'

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
    __tablename__ = 'team'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=True, unique=True)
    avatar_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))


class GithubInstallation(Base):
    __tablename__ = 'github_installation'
    
    installation_id: Mapped[int] = mapped_column(primary_key=True)
    _token: Mapped[str] = mapped_column('token', String(2048), nullable=True)
    token_expires_at: Mapped[datetime] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        SQLAEnum('active', 'deleted', 'suspended', name='github_installation_status'),
        nullable=False,
        default='active'
    )
    
    # Relationships
    projects: Mapped[list['Project']] = relationship(back_populates='github_installation')

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

    def __repr__(self):
        return f'<GithubInstallation {self.installation_id}>'


class Project(Base):
    __tablename__ = 'project'
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: token_hex(16))
    name: Mapped[str] = mapped_column(String(100), index=True)
    avatar_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repo_status: Mapped[str] = mapped_column(
        SQLAEnum('active', 'deleted', 'removed', 'transferred', name='project_github_status'),
        nullable=False,
        default='active'
    )
    github_installation_id: Mapped[int] = mapped_column(ForeignKey('github_installation.installation_id'), nullable=False, index=True)
    environments: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    _env_vars: Mapped[str] = mapped_column('env_vars', Text, nullable=False, default='')
    slug: Mapped[str] = mapped_column(String(40), nullable=True, unique=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id: Mapped[int] = mapped_column(ForeignKey('user.id'), index=True)
    status: Mapped[str] = mapped_column(
        SQLAEnum('active', 'paused', 'deleted', name='project_status'),
        nullable=False,
        default='active'
    )
    
    # Relationships
    user: Mapped[User] = relationship(back_populates='projects')
    github_installation: Mapped[GithubInstallation] = relationship(back_populates='projects')
    deployments: Mapped[list['Deployment']] = relationship(back_populates='project')

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

    def __repr__(self):
        return f'<Project {self.name}>'

    @property
    def active_environments(self) -> list[dict]:
        """Get active environments"""
        return [env for env in self.environments if env.get('status') == 'active']

    def get_environment_by_id(self, env_id: str) -> dict | None:
        """Get environment by ID"""
        return next((env for env in self.environments if env.get('id') == env_id), None)


class Deployment(Base):
    __tablename__ = 'deployment'
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: token_hex(16))
    project_id: Mapped[str] = mapped_column(ForeignKey('project.id'), index=True)
    repo: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    environment_id: Mapped[str] = mapped_column(String(8), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), index=True)
    commit_sha: Mapped[str] = mapped_column(String(40), index=True)
    commit_meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    _env_vars: Mapped[str] = mapped_column('env_vars', Text, nullable=False, default='')
    container_id: Mapped[str] = mapped_column(String(64), nullable=True)
    container_status: Mapped[str] = mapped_column(
        SQLAEnum('running', 'stopped', 'removed', name='deployment_container_status'),
        nullable=True
    )
    status: Mapped[str] = mapped_column(
        SQLAEnum('queued', 'in_progress', 'completed', name='deployment_status'),
        nullable=False,
        default='queued'
    )
    conclusion: Mapped[str] = mapped_column(
        SQLAEnum('succeeded', 'failed', 'canceled', 'skipped', name='deployment_conclusion'),
        nullable=True
    )
    trigger: Mapped[str] = mapped_column(
        SQLAEnum('webhook', 'user', 'api', name='deployment_trigger'),
        nullable=False,
        default='user'
    )
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    concluded_at: Mapped[datetime] = mapped_column(index=True, nullable=True)
    build_logs: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Relationships
    project: Mapped[Project] = relationship(back_populates='deployments')

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

    def __repr__(self):
        return f'<Deployment {self.id}>'

    @property
    def environment(self) -> dict | None:
        """Get environment details from project"""
        return self.project.get_environment_by_id(self.environment_id) if self.project else None


class Alias(Base):
    __tablename__ = 'alias'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    subdomain: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    deployment_id: Mapped[str] = mapped_column(ForeignKey('deployment.id'), index=True)
    previous_deployment_id: Mapped[str] = mapped_column(ForeignKey('deployment.id'), index=True, nullable=True)
    type: Mapped[str] = mapped_column(
        SQLAEnum('branch', 'environment', name='alias_type'),
        nullable=False
    )
    value: Mapped[str] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    deployment: Mapped[Deployment] = relationship(foreign_keys=[deployment_id])
    previous_deployment: Mapped[Deployment] = relationship(foreign_keys=[previous_deployment_id])

    def __repr__(self):
        return f'<Alias {self.subdomain}>' 