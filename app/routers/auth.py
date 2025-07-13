from typing import Annotated
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.responses import RedirectResponse, Response
from authlib.jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import resend
from datetime import timedelta
from typing import Any

from config import Settings, get_settings
from dependencies import (
    get_translation as _,
    flash,
    TemplateResponse,
    templates,
    get_current_user,
    get_github_oauth_client,
    get_github_primary_email,
)
from db import get_db
from models import User, UserIdentity, TeamInvite, TeamMember, utc_now
from forms.auth import EmailLoginForm
from utils.user import create_user_with_team, get_user_by_email, get_user_by_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


def create_session_cookie(user: User, settings: Settings) -> RedirectResponse:
    jwt_token = jwt.encode({"alg": "HS256"}, {"sub": user.id}, settings.secret_key)
    jwt_token_str = (
        jwt_token.decode("utf-8") if isinstance(jwt_token, bytes) else jwt_token
    )
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "auth_token",
        jwt_token_str,
        httponly=True,
        samesite="lax",
        secure=(settings.url_scheme == "https"),
        path="/",
    )
    return response


@router.api_route("/login", methods=["GET", "POST"], name="auth_login")
async def auth_login(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    try:
        current_user = await get_current_user(request, db, settings)
        if current_user:
            return RedirectResponse("/", status_code=303)
    except HTTPException:
        pass

    form: Any = await EmailLoginForm.from_formdata(request)

    if request.method == "POST" and await form.validate_on_submit():
        email = form.email.data
        expires_at = utc_now() + timedelta(minutes=15)
        token_payload = {
            "email": email,
            "exp": int(expires_at.timestamp()),
            "type": "email_login",
        }
        magic_token = jwt.encode({"alg": "HS256"}, token_payload, settings.secret_key)
        magic_token_str = (
            magic_token.decode("utf-8")
            if isinstance(magic_token, bytes)
            else magic_token
        )

        verify_link = str(
            request.url_for("auth_email_verify").include_query_params(
                token=magic_token_str
            )
        )

        resend.api_key = settings.resend_api_key

        try:
            resend.Emails.send(
                {
                    "from": f"{settings.email_sender_name} <{settings.email_sender_address}>",
                    "to": [email],
                    "subject": _("Sign in to %(app_name)s", app_name=settings.app_name),
                    "html": templates.get_template("email/login.html").render(
                        {
                            "request": request,
                            "email": email,
                            "verify_link": verify_link,
                            "email_logo": settings.email_logo
                            or request.url_for("static", path="logo-email.png"),
                            "app_name": settings.app_name,
                            "app_description": settings.app_description,
                            "app_url": f"{settings.url_scheme}://app.{settings.base_domain}",
                        }
                    ),
                }
            )
            flash(
                request,
                _(
                    "We just sent a login link to %(email)s, please check your inbox.",
                    email=email,
                ),
                "success",
            )
            if request.headers.get("HX-Request"):
                return Response(
                    status_code=200,
                    headers={"HX-Redirect": str(request.url_for("auth_login"))},
                )
            else:
                return RedirectResponse(request.url_for("auth_login"))

        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            flash(
                request,
                _(
                    "Uh oh, something went wrong. We couldn't send a login link to %(email)s. Please try again.",
                    email=email,
                ),
                "error",
            )

    return TemplateResponse(
        request=request,
        name="auth/partials/_form-email.html"
        if request.headers.get("HX-Request")
        else "auth/pages/login.html",
        context={"form": form},
    )


@router.get("/email/verify", name="auth_email_verify")
async def auth_email_verify(
    request: Request,
    token: str,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    try:
        current_user = None
        try:
            current_user = await get_current_user(request, db, settings)
        except HTTPException:
            pass

        payload = jwt.decode(token, settings.secret_key)
        token_type = payload.get("type")

        if token_type == "email_login":
            if current_user:
                flash(
                    request,
                    _(
                        'You are already logged in as "%(name)s" (%(email)s). Please log out first to sign in with %(login_email)s.',
                        name=current_user.name or current_user.username,
                        email=current_user.email,
                        login_email=payload.get("email"),
                    ),
                    "warning",
                )
                return RedirectResponse("/", status_code=303)

            email = payload.get("email")
            if not email:
                if current_user:
                    flash(request, _("Invalid or expired invitation."), "error")
                    return RedirectResponse("/", status_code=303)
                else:
                    raise HTTPException(status_code=400, detail="Invalid token")

            user = await get_user_by_email(db, email)
            if not user:
                user = await create_user_with_team(db, email)
                await db.commit()
                await db.refresh(user)

            return create_session_cookie(user, settings)

        elif token_type == "email_change":
            user_id = payload.get("user_id")
            new_email = payload.get("new_email")

            if not user_id or not new_email:
                raise HTTPException(status_code=400, detail="Invalid token")

            user = await db.get(User, user_id)
            if user:
                user.email = new_email
                await db.commit()

            flash(request, _("Email address updated successfully."), "success")
            return RedirectResponse("/settings", status_code=303)

        elif token_type == "team_invite":
            invite_id = payload.get("invite_id")
            email = payload.get("email", "")

            invite = await db.scalar(
                select(TeamInvite)
                .options(selectinload(TeamInvite.team))
                .where(TeamInvite.id == invite_id, TeamInvite.status == "pending")
            )

            if not invite or invite.expires_at < utc_now():
                if current_user:
                    flash(request, _("Invalid or expired invitation."), "error")
                    return RedirectResponse("/", status_code=303)
                else:
                    raise HTTPException(status_code=400, detail="Invalid token")

            if current_user:
                if current_user.email.lower() != email.lower():
                    flash(
                        request,
                        _(
                            'This invitation is for "%(email)s". Please log out and sign in with that email to accept the invitation.',
                            email=email,
                        ),
                        "error",
                    )
                    return RedirectResponse("/", status_code=303)

                existing_member = await db.scalar(
                    select(TeamMember).where(
                        TeamMember.team_id == invite.team_id,
                        TeamMember.user_id == current_user.id,
                    )
                )
                if existing_member:
                    flash(request, _("You are already a member of this team."), "info")
                    return RedirectResponse(f"/{invite.team.slug}", status_code=303)

                invite.status = "accepted"
                db.add(
                    TeamMember(
                        team_id=invite.team_id,
                        user_id=current_user.id,
                        role=invite.role,
                    )
                )
                await db.commit()

                flash(
                    request,
                    _(
                        'You have accepted the invitation to join "%(team_name)s".',
                        team_name=invite.team.name,
                    ),
                    "success",
                )
                return RedirectResponse(f"/{invite.team.slug}", status_code=303)
            else:
                user = await get_user_by_email(db, email)
                if not user:
                    user = await create_user_with_team(db, email)

                invite.status = "accepted"
                db.add(
                    TeamMember(
                        team_id=invite.team_id, user_id=user.id, role=invite.role
                    )
                )
                await db.commit()

                flash(
                    request,
                    _(
                        'You have accepted the invitation to join "%(team_name)s".',
                        team_name=invite.team.name,
                    ),
                    "success",
                )
                response = create_session_cookie(user, settings)
                response.headers["location"] = f"/{invite.team.slug}"
                return response

        else:
            raise HTTPException(status_code=400, detail="Invalid token type")

    except Exception:
        raise HTTPException(status_code=500, detail="Invalid or expired token")


@router.get("/github", name="auth_github_login")
async def auth_github_login(
    request: Request,
    oauth_client=Depends(get_github_oauth_client),
):
    if not oauth_client.github:
        raise HTTPException(
            status_code=500, detail="GitHub OAuth client not configured"
        )
    return await oauth_client.github.authorize_redirect(
        request, request.url_for("auth_github_callback")
    )


@router.get("/github/callback", name="auth_github_callback")
async def auth_github_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: AsyncSession = Depends(get_db),
    oauth_client=Depends(get_github_oauth_client),
):
    if not oauth_client.github:
        raise HTTPException(
            status_code=500, detail="GitHub OAuth client not configured"
        )

    token = await oauth_client.github.authorize_access_token(request)
    response = await oauth_client.github.get("user", token=token)
    gh_user = response.json()

    user = await get_user_by_provider(db, "github", str(gh_user["id"]))

    if user:
        result = await db.execute(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id, UserIdentity.provider == "github"
            )
        )
        github_identity = result.scalar_one_or_none()
        if github_identity:
            github_identity.access_token = token["access_token"]
            github_identity.provider_metadata = {
                "login": gh_user["login"],
                "name": gh_user.get("name"),
            }
    else:
        email = await get_github_primary_email(oauth_client, token)
        if email:
            user = await get_user_by_email(db, email)

        if not user:
            user = await create_user_with_team(
                db,
                email=email or f"{gh_user['login']}@github.local",
                name=gh_user.get("name"),
                username=gh_user["login"],
            )

        github_identity = UserIdentity(
            user_id=user.id,
            provider="github",
            provider_user_id=str(gh_user["id"]),
            access_token=token["access_token"],
            provider_metadata={
                "login": gh_user["login"],
                "name": gh_user.get("name"),
            },
        )
        db.add(github_identity)

    await db.commit()
    await db.refresh(user)
    return create_session_cookie(user, settings)


@router.get("/logout", name="auth_logout")
async def auth_logout():
    response = RedirectResponse("/auth/login")
    response.delete_cookie("auth_token")
    return response
