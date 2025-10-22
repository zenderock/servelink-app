from typing import Annotated
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.responses import RedirectResponse
from authlib.jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
import resend
from services.onesignal import OneSignalService
from datetime import timedelta
from typing import Any
import secrets

from config import Settings, get_settings
from dependencies import (
    get_translation as _,
    flash,
    TemplateResponse,
    templates,
    get_current_user,
    RedirectResponseX,
    get_github_oauth_client,
    get_github_primary_email,
    get_google_oauth_client,
    get_google_user_info,
)
from db import get_db
from models import User, UserIdentity, TeamInvite, TeamMember, Team, utc_now
from forms.auth import EmailLoginForm
from utils.user import sanitize_username, get_user_by_email, get_user_by_provider
from utils.access import is_email_allowed, notify_denied

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


async def _create_user_with_team(
    db: AsyncSession,
    email: str,
    name: str | None = None,
    username: str | None = None,
) -> User:
    if not username:
        username = email.split("@")[0]

    base_username = sanitize_username(username)

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
    
    # Assign free plan to new team
    from services.pricing import PricingService
    pricing_service = PricingService()
    await pricing_service.assign_free_plan_to_team(team, db)

    return user


def _create_session_cookie(user: User, settings: Settings) -> RedirectResponse:
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
        if not is_email_allowed(email, settings.access_rules_path):
            await notify_denied(
                email,
                "email",
                request,
                settings.access_denied_webhook,
            )
            flash(request, _(settings.access_denied_message), "error")
            return RedirectResponseX(
                request.url_for("auth_login"),
                status_code=303,
                request=request,
            )
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

        # Send email via OneSignal
        async with OneSignalService(settings) as onesignal:
            try:
                html_content = templates.get_template("email/login.html").render(
                    {
                        "request": request,
                        "email": email,
                        "verify_link": verify_link,
                        "email_logo": settings.email_logo
                        or request.url_for("assets", path="logo-email.png"),
                        "app_name": settings.app_name,
                        "app_description": settings.app_description,
                        "app_url": f"{settings.url_scheme}://{settings.app_hostname}",
                    }
                )
                
                await onesignal.send_email(
                    to_email=email,
                    subject=_("Sign in to %(app_name)s", app_name=settings.app_name),
                    html_content=html_content,
                    from_name=settings.email_sender_name,
                    from_address=settings.email_sender_address
                )
                
                flash(
                    request,
                    _(
                        "We just sent a login link to %(email)s, please check your inbox.",
                        email=email,
                    ),
                    "success",
                )
                return RedirectResponseX(
                    request.url_for("auth_login"), status_code=303, request=request
                )

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
        context={
            "form": form,
            "has_google_login": bool(
                settings.google_client_id and settings.google_client_secret
            ),
            "login_header": settings.login_header,
        },
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
                raise HTTPException(status_code=400, detail="Invalid token")

            user = await get_user_by_email(db, email)
            if not user:
                if not is_email_allowed(email, settings.access_rules_path):
                    await notify_denied(
                        email,
                        "email",
                        request,
                        settings.access_denied_webhook,
                    )
                    flash(request, _(settings.access_denied_message), "error")
                    return RedirectResponse("/auth/login", status_code=303)
                user = await _create_user_with_team(db, email)
                await db.commit()
                await db.refresh(user)

            return _create_session_cookie(user, settings)

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
                    user = await _create_user_with_team(db, email)

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
                response = _create_session_cookie(user, settings)
                response.headers["location"] = f"/{invite.team.slug}"
                return response

        else:
            raise HTTPException(status_code=400, detail="Invalid token type")

    except Exception:
        flash(request, _("Invalid or expired invitation."), "error")
        return RedirectResponse("/", status_code=303)


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
            if email and not is_email_allowed(email, settings.access_rules_path):
                await notify_denied(
                    email,
                    "github",
                    request,
                    settings.access_denied_webhook,
                )
                flash(request, _(settings.access_denied_message), "error")
                return RedirectResponse("/auth/login", status_code=303)
            user = await _create_user_with_team(
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
    return _create_session_cookie(user, settings)


@router.get("/google", name="auth_google_login")
async def auth_google_login(
    request: Request,
    oauth_client=Depends(get_google_oauth_client),
    settings: Settings = Depends(get_settings),
):
    if not oauth_client.google:
        raise HTTPException(
            status_code=500, detail="Google OAuth client not configured"
        )
    return await oauth_client.google.authorize_redirect(
        request, request.url_for("auth_google_callback")
    )


@router.get("/google/callback", name="auth_google_callback")
async def auth_google_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: AsyncSession = Depends(get_db),
    oauth_client=Depends(get_google_oauth_client),
):
    try:
        if not oauth_client.google:
            raise HTTPException(
                status_code=500, detail="Google OAuth client not configured"
            )

        token = await oauth_client.google.authorize_access_token(request)
        google_user_info = await get_google_user_info(oauth_client, token)

        if not google_user_info:
            flash(request, _("Failed to get user info from Google"), "error")
            return RedirectResponse("/auth/login", status_code=303)

        user = await get_user_by_provider(db, "google", google_user_info["id"])

        if user:
            result = await db.execute(
                select(UserIdentity).where(
                    UserIdentity.user_id == user.id, UserIdentity.provider == "google"
                )
            )
            google_identity = result.scalar_one_or_none()
            if google_identity:
                google_identity.access_token = token["access_token"]
                google_identity.provider_metadata = {
                    "email": google_user_info["email"],
                    "name": google_user_info.get("name"),
                    "picture": google_user_info.get("picture"),
                }
        else:
            email = google_user_info["email"]
            user = await get_user_by_email(db, email)

            if not user:
                if not is_email_allowed(email, settings.access_rules_path):
                    await notify_denied(
                        email,
                        "google",
                        request,
                        settings.access_denied_webhook,
                    )
                    flash(request, _(settings.access_denied_message), "error")
                    return RedirectResponse("/auth/login", status_code=303)
                user = await _create_user_with_team(
                    db,
                    email=email,
                    name=google_user_info.get("name"),
                )

            google_identity = UserIdentity(
                user_id=user.id,
                provider="google",
                provider_user_id=google_user_info["id"],
                access_token=token["access_token"],
                provider_metadata={
                    "email": google_user_info["email"],
                    "name": google_user_info.get("name"),
                    "picture": google_user_info.get("picture"),
                },
            )
            db.add(google_identity)

        await db.commit()
        await db.refresh(user)
        return _create_session_cookie(user, settings)
    except Exception:
        flash(request, _("Google login failed"), "error")
        return RedirectResponse("/auth/login", status_code=303)


@router.get("/logout", name="auth_logout")
async def auth_logout():
    response = RedirectResponse("/auth/login")
    response.delete_cookie("auth_token")
    return response
