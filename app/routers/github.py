from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from dependencies import (
    get_current_user,
    get_github_client,
    get_github_oauth_client,
    TemplateResponse,
    flash,
    get_db,
    get_translation as _,
)
from models import User, UserIdentity, GithubInstallation
from services.github import GitHub
from utils.user import get_user_github_token
from config import get_settings

router = APIRouter(prefix="/api/github")


@router.get("/repo-select", name="github_repo_select")
async def github_repo_select(
    request: Request,
    account: str | None = None,
    current_user: User = Depends(get_current_user),
    github_client: GitHub = Depends(get_github_client),
    db: AsyncSession = Depends(get_db),
):
    accounts = []
    selected_account = None
    has_github_oauth_token = False

    try:
        github_oauth_token = await get_user_github_token(db, current_user)
        if not github_oauth_token:
            has_github_oauth_token = False
        else:
            has_github_oauth_token = True
            installations = await github_client.get_user_installations(
                github_oauth_token
            )
            accounts = [
                installation["account"]["login"] for installation in installations
            ]
            selected_account = account or (accounts[0] if accounts else None)

    except Exception as e:
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in [
            401,
            403,
        ]:
            has_github_oauth_token = False
            flash(
                request,
                _(
                    "GitHub token has expired or is invalid. Please reconnect your account."
                ),
                "warning",
            )
        else:
            flash(request, _("Error fetching installations from GitHub."), "error")

    return TemplateResponse(
        request=request,
        name="github/partials/_repo-select.html",
        context={
            "current_user": current_user,
            "accounts": accounts,
            "selected_account": selected_account,
            "has_github_oauth_token": has_github_oauth_token,
        },
    )


@router.get("/repo-list", name="github_repo_list")
async def github_repo_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    github: GitHub = Depends(get_github_client),
    account: str | None = None,
    query: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    github_oauth_token = await get_user_github_token(db, current_user)
    repos = await github.search_user_repositories(
        github_oauth_token or "", account or "", query or ""
    )
    return TemplateResponse(
        request=request,
        name="github/partials/_repo-select-list.html",
        context={"repos": repos},
    )


@router.get("/authorize", name="github_oauth_authorize")
async def github_oauth_authorize(
    request: Request,
    next: str | None = None,
    current_user: User = Depends(get_current_user),
    oauth_client=Depends(get_github_oauth_client),
):
    """Authorize GitHub OAuth for account linking"""
    if not oauth_client.github:
        flash(request, _("GitHub OAuth not configured."), "error")
        redirect_url = next or request.headers.get("Referer", "/")
        return RedirectResponse(redirect_url, status_code=303)

    redirect_url = next or request.headers.get("Referer", "/")
    request.session["redirect_after_github"] = redirect_url

    return await oauth_client.github.authorize_redirect(
        request, request.url_for("github_oauth_authorize_callback")
    )


@router.get("/authorize/callback", name="github_oauth_authorize_callback")
async def github_oauth_authorize_callback(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    github_client: GitHub = Depends(get_github_client),
    oauth_client=Depends(get_github_oauth_client),
):
    """Handle GitHub OAuth callback for account linking"""

    redirect_url = request.session.pop("redirect_after_github", "/")

    if not oauth_client.github:
        flash(request, _("GitHub OAuth not configured."), "error")
        return RedirectResponse(redirect_url, status_code=303)

    try:
        token = await oauth_client.github.authorize_access_token(request)
        response = await oauth_client.github.get("user", token=token)
        github_user = response.json()

        result = await db.execute(
            select(UserIdentity).where(
                UserIdentity.user_id == current_user.id,
                UserIdentity.provider == "github",
            )
        )
        github_identity = result.scalar_one_or_none()

        if github_identity:
            github_identity.access_token = token["access_token"]
            github_identity.provider_metadata = {
                "login": github_user["login"],
                "name": github_user.get("name"),
            }
        else:
            github_identity = UserIdentity(
                user_id=current_user.id,
                provider="github",
                provider_user_id=str(github_user["id"]),
                access_token=token["access_token"],
                provider_metadata={
                    "login": github_user["login"],
                    "name": github_user.get("name"),
                },
            )
            db.add(github_identity)

        await db.commit()
        flash(request, _("GitHub account connected successfully!"), "success")

    except Exception:
        flash(request, _("Error connecting GitHub account."), "error")

    return RedirectResponse(redirect_url, status_code=303)


@router.get("/install", name="github_app_install")
async def github_app_install(
    request: Request,
    next: str | None = None,
    current_user: User = Depends(get_current_user),
):
    """Install GitHub App on new organizations"""
    settings = get_settings()

    if not settings.github_app_id:
        flash(request, _("GitHub App not configured."), "error")
        redirect_url = next or request.headers.get("Referer", "/")
        return RedirectResponse(redirect_url, status_code=303)

    request.session["redirect_after_install"] = next or request.headers.get(
        "Referer", "/"
    )

    return RedirectResponse(
        f"https://github.com/apps/{settings.github_app_name}/installations/new",
        status_code=303,
    )


@router.get("/install/callback", name="github_app_install_callback")
async def github_app_install_callback(
    request: Request,
    installation_id: int,
    setup_action: str,
    current_user: User = Depends(get_current_user),
    github_client: GitHub = Depends(get_github_client),
    db: AsyncSession = Depends(get_db),
):
    """Handle GitHub App installation callback"""
    redirect_url = request.session.pop("redirect_after_install", "/")

    if setup_action != "install":
        flash(request, _("GitHub App installation was not completed."), "warning")
        return RedirectResponse(redirect_url, status_code=303)

    try:
        # Make sure installation exists
        await github_client.get_installation(str(installation_id))

        result = await db.execute(
            select(GithubInstallation).where(
                GithubInstallation.installation_id == installation_id
            )
        )
        existing_installation = result.scalar_one_or_none()

        if existing_installation:
            existing_installation.status = "active"
            await db.commit()
            flash(
                request, _("GitHub App installation updated successfully!"), "success"
            )
        else:
            github_installation = GithubInstallation(
                installation_id=installation_id, status="active"
            )
            db.add(github_installation)
            await db.commit()
            flash(request, _("GitHub App installed successfully!"), "success")

    except Exception:
        flash(request, _("Error processing GitHub App installation."), "error")

    return RedirectResponse(redirect_url, status_code=303)


@router.get("/manage", name="github_app_manage")
async def github_app_manage(
    request: Request,
    next: str | None = None,
    current_user: User = Depends(get_current_user),
):
    """Manage existing GitHub App installations"""
    from config import get_settings

    settings = get_settings()

    if not settings.github_app_name:
        flash(request, _("GitHub App not configured."), "error")
        redirect_url = next or request.headers.get("Referer", "/")
        return RedirectResponse(redirect_url, status_code=303)

    return RedirectResponse(
        f"https://github.com/settings/installations/{settings.github_app_id}",
        status_code=303,
    )
