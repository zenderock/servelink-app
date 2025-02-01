from flask import current_app
from cryptography.fernet import Fernet
from flask_login import UserMixin
from app import db, login
from sqlalchemy import BigInteger, JSON, String, Text, ForeignKey, func, Enum as SQLAEnum
from sqlalchemy.orm import Mapped, mapped_column, WriteOnlyMapped, relationship
from datetime import datetime
from uuid import uuid4
import json
from secrets import token_urlsafe
from enum import Enum


class User(UserMixin, db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(index=True, unique=True)
    email: Mapped[str] = mapped_column(String(320), index=True, unique=True)
    username: Mapped[str] = mapped_column(String(50), index=True, unique=True)
    name: Mapped[str] = mapped_column(String(256), index=True, nullable=True)
    _github_token: Mapped[str] = mapped_column('github_token', String(2048), nullable=True)
    projects: WriteOnlyMapped['Project'] = relationship(
    back_populates='user')

    def __repr__(self):
        return '<User {}>'.format(self.email)

    @property
    def avatar(self):
        return f'https://unavatar.io/{self.email.lower()}'

    @property
    def github_token(self) -> str | None:
        if self._github_token:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            return f.decrypt(self._github_token.encode()).decode()
        return None

    @github_token.setter
    def github_token(self, value: str):
        if value:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            self._github_token = f.encrypt(value.encode()).decode()
        else:
            self._github_token = None


@login.user_loader
def load_user(id: int) -> User | None:
    return db.session.get(User, int(id))


class GithubInstallation(db.Model):
    installation_id: Mapped[int] = mapped_column(primary_key=True)
    _token: Mapped[str] = mapped_column('token', String(2048), nullable=True)
    token_expires_at: Mapped[datetime] = mapped_column(nullable=True)

    @property
    def token(self) -> str:
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        return f.decrypt(self._token.encode()).decode()
    
    @token.setter
    def token(self, value: str):
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        self._token = f.encrypt(value.encode()).decode()

    def __repr__(self):
        return f'<GithubInstallationToken {self.installation_id}>'
    

# TODO: consider adding version and schema validation
class Configuration(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=func.now())


# TODO: consider adding format validation
class EnvironmentVariables(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    _value: Mapped[str] = mapped_column('value', Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=func.now())

    @property
    def value(self) -> dict:
        if self._value:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            decrypted = f.decrypt(self._value.encode()).decode()
            return json.loads(decrypted)
        return {}
    
    @value.setter
    def value(self, value: dict):
        json_str = json.dumps(value or {})
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        self._value = f.encrypt(json_str.encode()).decode()


# TODO: add checks constraints for status
class Project(db.Model):
    id: Mapped[str] = mapped_column(String(22), primary_key=True, default=lambda: token_urlsafe(16))
    name: Mapped[str] = mapped_column(String(100), index=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repo_branch: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    config_id: Mapped[str] = mapped_column(ForeignKey(Configuration.id), nullable=True)
    env_vars_id: Mapped[str] = mapped_column(ForeignKey(EnvironmentVariables.id), nullable=True)
    _config: Mapped[Configuration] = relationship()
    _env_vars: Mapped[EnvironmentVariables] = relationship()
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=func.now(), onupdate=func.now())
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id), index=True)
    user: Mapped[User] = relationship(back_populates='projects')
    status: Mapped[str] = mapped_column(String(50), nullable=False, default='active')
    active_deployment_id: Mapped[str] = mapped_column(
        ForeignKey('deployment.id', use_alter=True, name='fk_project_active_deployment'),
        nullable=True
    )
    active_deployment: Mapped['Deployment'] = relationship(foreign_keys=[active_deployment_id])
    deployments: WriteOnlyMapped['Deployment'] = relationship(
        back_populates='project',
        foreign_keys='Deployment.project_id'
    )

    @property
    def config(self) -> dict:
        return self._config.value if self._config else {}
    
    @config.setter
    def config(self, value: dict):
        current = self.config
        if json.dumps(value, sort_keys=True) != json.dumps(current, sort_keys=True):
            self._config = Configuration(value=value)

    @property
    def env_vars(self) -> list[dict[str, str]]:
        return self._env_vars.value if self._env_vars else []
    
    @env_vars.setter
    def env_vars(self, value: list[dict[str, str]]):
        current = self.env_vars
        if current != value:  # Simple list comparison preserves order
            self._env_vars = EnvironmentVariables(value=value)

    def __repr__(self):
        return f'<Project {self.name}>'
    

# TODO: add checks constraints for status and conclusion
class Deployment(db.Model):
    id: Mapped[str] = mapped_column(String(22), primary_key=True, default=lambda: token_urlsafe(16))
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    project: Mapped[Project] = relationship(back_populates='deployments', foreign_keys=[project_id])
    repo: Mapped[dict] = mapped_column(JSON, nullable=False)
    config_id: Mapped[int] = mapped_column(ForeignKey(Configuration.id), nullable=False)
    env_vars_id: Mapped[int] = mapped_column(ForeignKey(EnvironmentVariables.id), nullable=False)
    config: Mapped[Configuration] = relationship()
    env_vars: Mapped[EnvironmentVariables] = relationship()
    commit_sha: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=func.now())
    concluded_at: Mapped[datetime] = mapped_column(index=True, nullable=True) 

    def __init__(self, project: Project, **kwargs):
        with db.session.no_autoflush:
            super().__init__(**kwargs)
            self.project = project
            # Snapshot repo, config and env_vars from project at time of creation
            self.repo = {
                'id': project.repo_id,
                'full_name': project.repo_full_name,
                'branch': project.repo_branch
            }
            self.config_id = project._config.id if project._config else None
            self.env_vars_id = project._env_vars.id if project._env_vars else None

    def __repr__(self):
        return f'<Deployment {self.id}>'