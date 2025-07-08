from typing import Annotated
from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from authlib.jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import Settings, get_settings
from dependencies import templates
from db import get_db
from models import User, Team, TeamMember

router = APIRouter(prefix="/auth")


def create_oauth_client(settings: Settings) -> OAuth:
    oauth = OAuth()
    oauth.register(
        "github",
        client_id=settings.github_app_client_id,
        client_secret=settings.github_app_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
    )
    return oauth


@router.get("/login", name="auth_login")
async def login(request: Request):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
    )


@router.get("/github", name="github_login")
async def github_login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)]
):
    oauth = create_oauth_client(settings)
    if not oauth.github:
        raise HTTPException(status_code=500, detail="GitHub OAuth client not configured")
    return await oauth.github.authorize_redirect(
        request,
        request.url_for("github_callback")
    )


@router.get("/github/callback", name="github_callback")
async def github_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: AsyncSession = Depends(get_db)
):
    oauth = create_oauth_client(settings)
    if not oauth.github:
        raise HTTPException(status_code=500, detail="GitHub OAuth client not configured")
    token = await oauth.github.authorize_access_token(request)
    response = await oauth.github.get("user", token=token)
    gh_user = response.json()
    
    result = await db.execute(
        select(User).where(User.github_id == gh_user["id"])
    )
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            github_id=gh_user["id"],
            email=gh_user.get("email", ""),
            username=gh_user["login"],
            name=gh_user.get("name", ""),
            github_token=token["access_token"]
        )
        db.add(user)
        await db.flush()

        # Create default team for this user and make them the owner.
        team = Team(name=f"{user.name or user.username}")
        db.add(team)
        await db.flush()
        user.default_team_id = team.id
        db.add(TeamMember(team_id=team.id, user_id=user.id, role="owner"))
        
        await db.commit()
        await db.refresh(user)
    else:
        user.github_token = token["access_token"]
        await db.commit()

    jwt_token = jwt.encode(
        {"alg": "HS256"},
        {"sub": user.id},
        settings.secret_key
    )
    jwt_token_str = jwt_token.decode('utf-8') if isinstance(jwt_token, bytes) else jwt_token
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "auth_token",
        jwt_token_str,
        httponly=True,
        samesite="lax",
        secure= (settings.url_scheme == "https"),
        path="/"
    )
    return response


@router.get("/logout", name="auth_logout")
async def logout():
    response = RedirectResponse("/auth/login")
    response.delete_cookie("auth_token")
    return response