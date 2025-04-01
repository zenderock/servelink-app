from __future__ import annotations
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
from app.helpers.colors import get_project_color


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
        SQLAEnum('active', 'deleted', 'suspended', name='github_installation_status'),
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
    avatar_updated_at = db.Column(db.DateTime, nullable=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
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
    environments: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=[])
    _env_vars: Mapped[str] = mapped_column('env_vars', Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(40), nullable=True, unique=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default={})
    created_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(index=True, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id), index=True)
    user: Mapped[User] = relationship(back_populates='projects')
    status: Mapped[str] = mapped_column(
        SQLAEnum('active', 'paused', 'deleted', name='project_status'),
        nullable=False,
        default='active'
    )
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
    
    @property
    def hostname(self) -> str:
        return f"{self.slug}.{current_app.config['BASE_DOMAIN']}"
    
    @property
    def url(self) -> str:
        return f"{current_app.config['URL_SCHEME']}://{self.hostname}"
    
    @property
    def aliases(self) -> list[str]:
        if self.promoted_deployment:
            return [self.promoted_deployment.aliases]
        return []
    
    @property
    def promoted_deployment(self) -> Deployment | None:
        # TODO: add a flag for promoted deployment (rollback)
        deployment = db.session.scalar(
            select(Deployment)
            .where(
                Deployment.project_id == self.id,
                Deployment.conclusion == 'succeeded',
                # Deployment.environment == 'production'
            )
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        print(deployment.id)
        return deployment

    @property
    def color(self) -> str:
        return get_project_color(self.id)
    
    @env_vars.setter
    def env_vars(self, value: list[dict[str, str]] | None):
        json_str = json.dumps(value or [])
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        self._env_vars = f.encrypt(json_str.encode()).decode()

    def __repr__(self):
        return f'<Project {self.name}>'

    def get_config(self, environment: str | None = None) -> dict:
        """Get complete project configuration with framework defaults."""
        framework_slug = self.config.get('framework', 'python')
        framework = next((f for f in current_app.frameworks if f.get('slug') == framework_slug), {})

        return {
            'framework': framework,
            'build_command': self.config.get('build_command') or framework.get('build_command'),
            'pre_deploy_command': self.config.get('pre_deploy_command') or framework.get('pre_deploy_command'),
            'start_command': self.config.get('start_command') or framework.get('start_command'),
            'root_directory': self.config.get('root_directory') or framework.get('root_directory', './'),
        }
    
    def get_env_vars(self, environment: str) -> list[dict[str, str]]:
        """Flattened env vars for a specific environment."""
        env_vars = [var for var in self.env_vars if not var.get('environment')]
        for var in self.env_vars:
            if var.get('environment') == environment:
                env_vars = [v for v in env_vars if v['key'] != var['key']] # Remove dupes
                env_vars.append(var)
        return env_vars

    def has_active_environment_with_slug(self, slug: str, exclude_id: str | None = None) -> bool:
        """Check if an active environment with given slug exists"""
        return any(e for e in self.active_environments 
                  if e['slug'] == slug and (exclude_id is None or e['id'] != exclude_id))

    def create_environment(self, name: str, slug: str, **kwargs) -> dict:
        """Create a new environment with a unique ID"""
        if self.has_active_environment_with_slug(slug):
            raise ValueError(f"An active environment with slug '{slug}' already exists")

        env = {
            'id': token_hex(4),
            'name': name,
            'slug': slug,
            'status': 'active',
            **kwargs
        }
        environments = self.environments.copy()
        environments.append(env)
        self.environments = environments
        return env

    def update_environment(self, environment_id: str, **updates) -> dict | None:
        """Update environment"""
        env = self.get_environment_by_id(environment_id)
        if not env:
            return None
        
        # Prevent production rename
        if env['slug'] == 'production' and ('name' in updates or 'slug' in updates):
            raise ValueError("Cannot delete production environment")

        # If changing slug, check it's unique
        new_slug = updates.get('slug')
        if new_slug and new_slug != env['slug'] and self.has_active_environment_with_slug(new_slug, exclude_id=environment_id):
            raise ValueError(f"An active environment with slug '{new_slug}' already exists")

        # Update the environment
        env_index = next(i for i, e in enumerate(self.environments) if e['id'] == environment_id)
        old_slug = self.environments[env_index]['slug']
        
        environments = self.environments.copy()
        environments[env_index] = {
            **environments[env_index],
            **updates
        }
        self.environments = environments

        # Update env vars if slug changed
        if new_slug and new_slug != old_slug:
            env_vars = self.env_vars.copy()
            for var in env_vars:
                if var.get('environment') == old_slug:
                    var['environment'] = new_slug
            self.env_vars = env_vars

        return environments[env_index]

    def delete_environment(self, environment_id: str) -> bool:
        """Soft delete environment"""
        if environment_id == 'prod':
            raise ValueError("Cannot delete production environment")
        
        env = self.get_environment_by_id(environment_id)
        if not env:
            return False

        # Remove env vars for this environment (still need slug here)
        env_vars = self.env_vars.copy()
        env_vars = [var for var in env_vars if var.get('environment') != env['slug']]
        self.env_vars = env_vars

        # Mark environment as deleted
        env_index = next(i for i, e in enumerate(self.environments) if e['id'] == environment_id)
        environments = self.environments.copy()
        environments[env_index] = {
            **environments[env_index],
            'status': 'deleted'
        }
        self.environments = environments
        return True

    @property
    def active_environments(self) -> list[dict]:
        """Get only active environments"""
        return [env for env in self.environments 
                if env.get('status') == 'active']

    def get_environment_by_id(self, env_id: str) -> dict | None:
        """Get environment by ID"""
        return next((env for env in self.environments if env['id'] == env_id), None)

    def get_environment_by_slug(self, slug: str, active_only: bool = True) -> dict | None:
        """Get environment by slug"""
        environments = self.active_environments if active_only else self.environments
        return next((env for env in environments if env['slug'] == slug), None)


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
    environment_id: Mapped[str] = mapped_column(String(8), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    _env_vars: Mapped[str] = mapped_column('env_vars', Text, nullable=False)
    commit: Mapped[dict] = mapped_column(JSON, nullable=False)
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
    aliases: Mapped[list['Alias']] = relationship(
        back_populates='deployment',
        foreign_keys='Alias.deployment_id'
    )

    @property
    def environment(self) -> dict | None:
        """Get environment configuration"""
        return self.project.get_environment_by_id(self.environment_id)

    @property
    def env_vars(self) -> list[dict[str, str]]:
        if self._env_vars:
            f = Fernet(current_app.config['ENCRYPTION_KEY'])
            decrypted = f.decrypt(self._env_vars.encode()).decode()
            return json.loads(decrypted)
        return []
    
    @property
    def slug(self) -> str:
        return f"{self.project.slug}-id-{self.id[:7]}"
    
    @property
    def hostname(self) -> str:
        return f"{self.slug}.{current_app.config['BASE_DOMAIN']}"
    
    @property
    def url(self) -> str:
        return f"{current_app.config['URL_SCHEME']}://{self.hostname}"
    
    @property
    def featured_slug(self) -> str | None:
        if not self.conclusion:
            return None
        # First try to find an environment alias
        env_alias = next(filter(lambda a: a.type == 'environment', self.aliases), None)
        if env_alias:
            return env_alias.subdomain
        # Then try to find a branch alias
        branch_alias = next(filter(lambda a: a.type == 'branch', self.aliases), None)
        if branch_alias:
            return branch_alias.subdomain
        return self.slug
        
    @property
    def featured_hostname(self) -> str | None:
        if not self.conclusion:
            return None
        return f"{self.featured_slug}.{current_app.config['BASE_DOMAIN']}"
    
    @property
    def featured_url(self) -> str | None:
        if not self.conclusion:
            return None
        return f"{current_app.config['URL_SCHEME']}://{self.featured_hostname}"
    
    @env_vars.setter 
    def env_vars(self, value: list[dict[str, str]] | None):
        json_str = json.dumps(value or [])
        f = Fernet(current_app.config['ENCRYPTION_KEY'])
        self._env_vars = f.encrypt(json_str.encode()).decode()

    def __init__(self, **kwargs):
        with db.session.no_autoflush:
            super().__init__(**kwargs)
            # Snapshot repo, config, environments and env_vars from project at time of creation
            project = kwargs['project']
            self.repo = {
                'id': project.repo_id,
                'full_name': project.repo_full_name
            }
            self.config = project.get_config()
            environment = project.get_environment_by_id(kwargs['environment_id'])
            self.env_vars = project.get_env_vars(environment['slug'])

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


class Alias(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    subdomain: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.id), index=True)
    deployment: Mapped[Deployment] = relationship(back_populates='aliases', foreign_keys=[deployment_id])
    type: Mapped[str] = mapped_column(
        SQLAEnum('branch', 'environment', name='alias_type'),
        nullable=True
    )
    value: Mapped[str] = mapped_column(String(255), nullable=True)

    @property
    def hostname(self) -> str:
        return f"{self.subdomain}.{current_app.config['BASE_DOMAIN']}"
    
    @property
    def url(self) -> str:
        return f"{current_app.config['URL_SCHEME']}://{self.hostname}"
    
    @classmethod
    def update_or_create(cls, subdomain: str, deployment_id: str, type: str, value: str = None):
        alias = cls.query.filter_by(subdomain=subdomain).first()
        if alias:
            alias.deployment_id = deployment_id
            alias.value = value
        else:
            alias = cls(
                subdomain=subdomain,
                deployment_id=deployment_id,
                type=type,
                value=value,
            )
            db.session.add(alias)
        return alias