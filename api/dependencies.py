from fastapi import Request, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from authlib.jose import jwt
from functools import lru_cache
import humanize
from datetime import datetime

from config import get_settings, Settings
from db import get_db
from models import User
from services.github import GitHub


@lru_cache()
def get_github_service() -> GitHub:
    settings = get_settings()
    return GitHub(
        client_id=settings.github_app_client_id,
        client_secret=settings.github_app_client_secret,
        app_id=settings.github_app_id,
        private_key=settings.github_app_private_key
    )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> User:
    """Get the current user object, redirect to login if not authenticated."""
    session = request.cookies.get("auth_token")
    if not session:
        raise HTTPException(
            status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required"
        )
    
    try:
        data = jwt.decode(session, settings.secret_key)
        user_id = data["sub"]
    except Exception:
        raise HTTPException(
            status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required"
        )
        
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required"
        )
    return user


def get_translation(key: str, **kwargs) -> str:
    """Simple translation function - for now just returns the key."""
    return key.format(**kwargs) if kwargs else key


def flash(request: Request, title: str, category: str = "info", description: str = None):
    if "_messages" not in request.session:
        request.session["_messages"] = []
    
    request.session["_messages"].append({
        "title": title,
        "category": category,
        "description": description
    })


def get_flashed_messages():
    try:
        from jinja2 import runtime
        context = runtime.get_current_context()
        request = context.get('request')
        if request and hasattr(request, 'session'):
            return request.session.pop("_messages", [])
    except:
        pass
    return []


def get_request_context():
    """Make request available globally in templates"""
    try:
        from jinja2 import runtime
        context = runtime.get_current_context()
        return context.get('request')
    except:
        return None


def timeago_filter(value):
    """Convert a datetime or ISO string to a human readable time ago."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return humanize.naturaltime(value)


templates = Jinja2Templates(directory="templates")
templates.env.globals["_"] = get_translation
templates.env.globals["config"] = get_settings()
templates.env.globals["get_flashed_messages"] = get_flashed_messages
templates.env.filters["timeago"] = timeago_filter

TemplateResponse = templates.TemplateResponse