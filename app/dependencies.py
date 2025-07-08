from fastapi import Request, Depends, HTTPException, status
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from authlib.jose import jwt
from functools import lru_cache
import humanize
from datetime import datetime
from redis.asyncio import Redis
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from config import get_settings, Settings
from db import get_db
from models import User, Project, Deployment, Team, TeamMember
from services.github import GitHub


@lru_cache
def get_github_client() -> GitHub:
    settings = get_settings()
    return GitHub(
        client_id=settings.github_app_client_id,
        client_secret=settings.github_app_client_secret,
        app_id=settings.github_app_id,
        private_key=settings.github_app_private_key,
    )


@lru_cache
def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def get_deployment_queue() -> ArqRedis:
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    return await create_pool(redis_settings)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Get the current user object, redirect to login if not authenticated."""
    session = request.cookies.get("auth_token")
    if not session:
        raise HTTPException(
            status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required",
        )

    try:
        data = jwt.decode(session, settings.secret_key)
        user_id = data["sub"]
    except Exception:
        raise HTTPException(
            status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required",
        )
    return user


def get_translation(key: str, **kwargs) -> str:
    """Simple translation helper.

    Supports gettext-style ``%(name)s`` placeholders so you can write
    _( "Delete \"%(name)s\"?", name=project.name )
    now and later replace this stub with real gettext without changing
    templates or routes.
    """
    if not kwargs:
        return key

    # 1. Try gettext-style placeholders: %(key)s
    try:
        return key % kwargs  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # 2. Fallback to str.format style placeholders: {key}
        return key.format(**kwargs)


def flash(
    request: Request, title: str, category: str = "info", description: str | None = None
):
    if "_messages" not in request.session:
        request.session["_messages"] = []

    request.session["_messages"].append(
        {"title": title, "category": category, "description": description}
    )


@pass_context
def get_flashed_messages(ctx):
    request = ctx.get("request")
    if request and hasattr(request, "session"):
        return request.session.pop("_messages", [])
    return []


async def get_team_by_slug(
    team_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> tuple[Team, TeamMember]:
    result = await db.execute(
        select(Team, TeamMember)
        .join(TeamMember)
        .where(
            Team.slug == team_slug,
            TeamMember.user_id == current_user.id,
            TeamMember.role.in_(["owner", "member"])
        )
        .limit(1)
    )
    team_and_membership = result.first()
    if not team_and_membership:
        raise HTTPException(status_code=404, detail="Team not found or access denied")
    
    team, team_member = team_and_membership
    return team, team_member


async def get_project_by_name(
    project_name: str,
    db: AsyncSession = Depends(get_db),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug)
) -> Project:
    team, membership = team_and_membership

    result = await db.execute(
        select(Project)
        .where(
            Project.name == project_name,
            Project.team_id == team.id,
            Project.status != "deleted",
        )
        .limit(1)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def get_project_by_id(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug)
) -> Project:
    team, membership = team_and_membership
    
    result = await db.execute(
        select(Project)
        .where(
            Project.id == project_id,
            Project.team_id == team.id,
            Project.status != "deleted",
        )
        .limit(1)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def get_deployment_by_id(
    deployment_id: str,
    db: AsyncSession = Depends(get_db)
) -> Deployment:
    result = await db.execute(
        select(Deployment)
        .options(selectinload(Deployment.aliases))
        .where(Deployment.id == deployment_id)
        .limit(1)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


def timeago_filter(value):
    """Convert a datetime or ISO string to a human readable time ago."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return humanize.naturaltime(value)


templates = Jinja2Templates(directory="templates")
templates.env.globals["_"] = get_translation
templates.env.globals["settings"] = get_settings()
templates.env.globals["get_flashed_messages"] = get_flashed_messages
templates.env.filters["timeago"] = timeago_filter


def TemplateResponse(
    request: Request,
    name: str,
    context: dict | None = None,
    status_code: int = 200,
    headers: dict | None = None,
    media_type: str | None = None,
    background: BackgroundTask | None = None,
):
    if request.headers.get("HX-Request"):
        """Render template wrapped in fragment layout for HTMX"""
        context = context or {}

        # Render the fragment template first
        template = templates.get_template(name)
        content = template.render(request=request, is_fragment=True, **context)

        # Return wrapped in fragment layout
        return templates.TemplateResponse(
            request=request,
            name="layouts/fragment.html",
            context={"content": content, **context},
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )
    else:
        """Regular template response"""
        return templates.TemplateResponse(
            request=request,
            name=name,
            context=context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )