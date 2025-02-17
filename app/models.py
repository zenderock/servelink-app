from flask import current_app
from cryptography.fernet import Fernet
from flask_login import UserMixin
from app import db, login
from sqlalchemy import BigInteger, JSON, String, Text, ForeignKey, Enum as SQLAEnum, event, select, update
from sqlalchemy.orm import Mapped, mapped_column, WriteOnlyMapped, relationship
from datetime import datetime, timezone
import json
from secrets import token_hex
import re


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
    status: Mapped[str] = mapped_column(
        SQLAEnum(
            'active',
            'deleted',    # Installation was deleted
            'suspended',  # Installation was suspended
            name='github_installation_status'
        ),
        nullable=False,
        default='active'
    )
    projects: WriteOnlyMapped['Project'] = relationship(
        back_populates='github_installation',
        foreign_keys='Project.github_installation_id'
    )

    # TODO: cache Fernet in Flask app context?

    @property
    def token(self) -> str:
        if self._token is None:
           return None
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        return f.decrypt(self._token.encode()).decode()
    
    @token.setter
    def token(self, value: str):
        if not value:
            self._token = None
        else:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            self._token = f.encrypt(value.encode()).decode()

    def __repr__(self):
        return f'<GithubInstallationToken {self.installation_id}>'


# TODO: add checks constraints for status
class Project(db.Model):
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: token_hex(16))
    name: Mapped[str] = mapped_column(String(100), index=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repo_branch: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repo_status: Mapped[str] = mapped_column(
        SQLAEnum(
            'active',
            'deleted',
            'removed',
            'transferred',
            name='project_github_status'
        ),
        nullable=False,
        default='active'
    )
    github_installation_id: Mapped[int] = mapped_column(ForeignKey(GithubInstallation.installation_id), nullable=False, index=True)
    github_installation: Mapped[GithubInstallation] = relationship(back_populates='projects')
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    _env_vars: Mapped[str] = mapped_column('env_vars', Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(40), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id), index=True)
    user: Mapped[User] = relationship(back_populates='projects')
    status: Mapped[str] = mapped_column(
        SQLAEnum('active', 'paused', 'deleted', name='project_status'),
        nullable=False,
        default='active'
    )
    mapping: Mapped[list[str]] = mapped_column(JSON, nullable=True, default={"environments": {}, "branches": {}})
    deployments: WriteOnlyMapped['Deployment'] = relationship(
        back_populates='project',
        foreign_keys='Deployment.project_id'
    )

    @property
    def env_vars(self) -> list[dict[str, str]]:
        if self._env_vars:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            decrypted = f.decrypt(self._env_vars.encode()).decode()
            return json.loads(decrypted)
        return []
    
    @env_vars.setter
    def env_vars(self, value: list[dict[str, str]] | None):
        json_str = json.dumps(value or [])
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        self._env_vars = f.encrypt(json_str.encode()).decode()

    def __repr__(self):
        return f'<Project {self.name}>'


@event.listens_for(Project, 'after_insert')
def set_project_slug(mapper, connection, project):
    """Generate and set slug after project is inserted (and has an ID)."""
    if not project.slug:
        # Convert to lowercase and replace dots/underscores with hyphens
        base_slug = f"{project.name}-{project.user.username}".lower().replace('.', '-').replace('_', '-')
        base_slug = re.sub(r'-+', '-', base_slug)
        base_slug = base_slug[:40]
        base_slug = base_slug.strip('-')
        
        # Try base slug first, if exists use ID version
        new_slug = base_slug if not connection.scalar(
            select(Project.slug).where(Project.slug == base_slug)
        ) else f"{base_slug[:32]}-{str(project.id)[:7]}"
        
        # Update both database and instance
        connection.execute(
            update(Project)
            .where(Project.id == project.id)
            .values(slug=new_slug)
        )
        project.slug = new_slug


class Deployment(db.Model):
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: token_hex(16))
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    project: Mapped[Project] = relationship(back_populates='deployments', foreign_keys=[project_id])
    repo: Mapped[dict] = mapped_column(JSON, nullable=False)
    container_id: Mapped[str] = mapped_column(String(64), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    _env_vars: Mapped[str] = mapped_column('env_vars', Text, nullable=False)
    commit: Mapped[dict] = mapped_column(JSON, nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=True, unique=True)
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

    @property
    def env_vars(self) -> list[dict[str, str]]:
        if self._env_vars:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            decrypted = f.decrypt(self._env_vars.encode()).decode()
            return json.loads(decrypted)
        return []
    
    def url(self, scheme: bool = True) -> str:
        relative_url = f"{self.project.name}-{self.project.user.username}-{self.id[:7]}.{current_app.config['BASE_DOMAIN']}"
        return f"{current_app.config['URL_SCHEME']}://{relative_url}" if scheme else relative_url
    
    @env_vars.setter
    def env_vars(self, value: list[dict[str, str]] | None):
        json_str = json.dumps(value or [])
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        self._env_vars = f.encrypt(json_str.encode()).decode()

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
            self.config = project.config
            self.env_vars = project.env_vars

    def __repr__(self):
        return f'<Deployment {self.id}>'

    def parse_logs(self):
        """Parse raw build logs into structured format."""
        if not self.build_logs:
            return []
        
        logs = []
        for line in self.build_logs.splitlines():
            try:
                timestamp, message = line.split(' ', 1)
                timestamp = datetime.fromisoformat(timestamp.rstrip('Z')).timestamp()
            except (ValueError, IndexError):
                timestamp = None
                message = line
            
            logs.append({
                'timestamp': timestamp,
                'message': message
            })
        return logs

    @property
    def parsed_logs(self):
        return self.parse_logs()
    
    @property
    def environment(self) -> str:
        # TODO: add support for multiple environments
        # TODO: account for changes in production branch + redeploy/rollback
        if self.commit.get('branch') == self.project.repo_branch:
            return 'production'
        return 'preview'
    
# class Subdomain(db.Model):
#     id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: token_hex(16))
#     slug: Mapped[str] = mapped_column(String(255), nullable=False)
#     deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.id), index=True)
#     deployment: Mapped[Deployment] = relationship(back_populates='urls', foreign_keys=[deployment_id])

#     def __repr__(self):
#         return f'<Url {self.url}>'
    