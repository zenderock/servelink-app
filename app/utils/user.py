from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
import re
import secrets

from models import User, UserIdentity, Team, TeamMember


def _sanitize_username(username: str) -> str:
    """Sanitize a name (for a user or a team)."""
    sanitized_name = username
    sanitized_name = sanitized_name.lower()
    sanitized_name = (
        sanitized_name.replace(" ", "-").replace("_", "-").replace(".", "-")
    )
    sanitized_name = re.sub(r"[^a-z0-9-]", "", sanitized_name)
    sanitized_name = re.sub(r"-+", "-", sanitized_name)
    sanitized_name = sanitized_name.strip("-")
    return sanitized_name


async def create_user_with_team(
    db: AsyncSession,
    email: str,
    name: str | None = None,
    username: str | None = None,
) -> User:
    if not username:
        username = email.split("@")[0]

    base_username = _sanitize_username(username)

    user = None
    for attempt in range(5):
        try:
            if attempt == 0:
                unique_username = base_username[:50]
            else:
                random_suffix = secrets.token_hex(2)
                unique_username = f"{base_username[:45]}-{random_suffix}"

            user = User(
                email=email.strip().lower(),
                name=name,
                username=unique_username,
                email_verified=True,
            )
            db.add(user)
            await db.flush()
            break

        except IntegrityError as e:
            await db.rollback()
            if "username" not in str(e):
                raise

    if not user or not user.id:
        raise RuntimeError("Failed to create user after maximum retries")

    team = Team(name=user.name or user.username, created_by_user_id=user.id)
    db.add(team)
    await db.flush()

    user.default_team_id = team.id
    db.add(TeamMember(team_id=team.id, user_id=user.id, role="owner"))

    return user


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(func.lower(User.email) == func.lower(email.strip()))
    )
    return result.scalar_one_or_none()


async def get_user_by_provider(
    db: AsyncSession, provider: str, provider_user_id: str
) -> User | None:
    result = await db.execute(
        select(User)
        .join(UserIdentity)
        .where(
            UserIdentity.provider == provider,
            UserIdentity.provider_user_id == provider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_user_github_token(db: AsyncSession, user: User) -> str | None:
    result = await db.execute(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id, UserIdentity.provider == "github"
        )
    )
    github_identity = result.scalar_one_or_none()
    return github_identity.access_token if github_identity else None
