from fastapi import Request
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import GithubInstallation, User, UserIdentity
from services.github import GitHub
from dependencies import flash, get_translation as _


async def get_installation_instance(
    installation_id: int,
    db: AsyncSession,
    github_client: GitHub,
) -> GithubInstallation:
    """
    Retrieve the GithubInstallation SQLAlchemy instance for a given installation.
    If no record exists, create one.
    If the token is missing or expired, refresh it.
    """
    result = await db.execute(
        select(GithubInstallation).where(
            GithubInstallation.installation_id == installation_id
        )
    )
    installation = result.scalar_one_or_none()

    if not installation:
        installation = GithubInstallation(installation_id=installation_id)
    if not installation.token or (
        installation.token_expires_at
        and installation.token_expires_at
        <= datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        token_data = await github_client.get_installation_access_token(
            str(installation_id)
        )
        installation.token = token_data["token"]
        installation.token_expires_at = datetime.fromisoformat(
            token_data["expires_at"].replace("Z", "+00:00")
        ).replace(tzinfo=None)

    installation = await db.merge(installation)
    await db.commit()
    return installation


async def revoke_oauth_access(
    request: Request,
    user: User,
    db: AsyncSession,
) -> bool:
    """Revoke OAuth access to GitHub"""
    try:
        result = await db.execute(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id,
                UserIdentity.provider == "github",
            )
        )
        github_identity = result.scalar_one_or_none()
        
        if github_identity:
            await db.delete(github_identity)
            await db.commit()
            flash(request, _("GitHub account disconnected successfully."), "success")
            return True
        else:
            flash(request, _("No GitHub account connected."), "warning")
            return False
    except Exception:
        flash(request, _("Error disconnecting GitHub account."), "error")
        return False