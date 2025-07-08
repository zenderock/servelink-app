import os
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import logging
from typing import Any

from models import Project, Deployment, User, Team, TeamMember, utc_now
from dependencies import (
    get_current_user,
    get_team_by_slug,
    get_deployment_queue,
    flash,
    get_translation as _,
    TemplateResponse
)
from config import get_settings, Settings
from db import get_db
from utils.pagination import paginate
from utils.teams import get_latest_teams
from forms.team import TeamDeleteForm, TeamGeneralForm, NewTeamForm

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/new-team", methods=["GET", "POST"], name="new_team")
async def new_team(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    form: Any = await NewTeamForm.from_formdata(request)

    print(request.method)
    print(form.name.data)
    if request.method == "POST" and await form.validate_on_submit():
        team = Team(name=form.name.data)
        db.add(team)
        await db.flush()
        db.add(TeamMember(team_id=team.id, user_id=current_user.id, role="owner"))
        await db.commit()

        return Response(
            status_code=200,
            headers={
                "HX-Redirect": str(
                    request.url_for("team_index", team_slug=team.slug)
                )
            },
        )

    return TemplateResponse(
        request=request,
        name="teams/partials/_dialog-new-team.html",
        context={
            "form": form,
        },
    )


@router.get("/{team_slug}", name="team_index")
async def team_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
):
    team, membership = team_and_membership

    projects_result = await db.execute(
        select(Project)
        .where(Project.team_id == team.id, Project.status != "deleted")
        .order_by(Project.updated_at.desc())
        .limit(6)
    )
    projects = projects_result.scalars().all()

    deployments_result = await db.execute(
        select(Deployment)
        .options(selectinload(Deployment.aliases))
        .join(Project)
        .where(Project.team_id == team.id)
        .order_by(Deployment.created_at.desc())
        .limit(10)
    )
    deployments = deployments_result.scalars().all()

    latest_teams = await get_latest_teams(db=db, current_team=team, limit=5)

    return TemplateResponse(
        request=request,
        name="teams/pages/index.html",
        context={
            "current_user": current_user,
            "team": team,
            "projects": projects,
            "deployments": deployments,
            "latest_teams": latest_teams,
        },
    )


@router.get('/{team_slug}/projects', name="team_projects")
async def team_projects(
    request: Request,
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    team, membership = team_and_membership

    per_page = 25

    query = (
        select(Project)
        .where(Project.team_id == team.id, Project.status != "deleted")
        .order_by(Project.updated_at.desc())
    )

    pagination = await paginate(db, query, page, per_page)

    latest_teams = await get_latest_teams(db=db, current_team=team, limit=5)

    return TemplateResponse(
        request=request,
        name="teams/pages/projects.html",
        context={
            "current_user": current_user,
            "team": team,
            "projects": pagination.get("items"),
            "pagination": pagination,
            "latest_teams": latest_teams,
        },
    )


@router.api_route('/{team_slug}/settings', methods=["GET", "POST"], name="team_settings")
async def team_settings(
    request: Request,
    fragment: str = Query(default="general"),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    team, membership = team_and_membership

    # Delete
    delete_team_form = None
    # Prevent deleting default teams
    result = await db.execute(select(User).where(User.default_team_id == team.id))
    is_default_team = result.scalar_one_or_none()
    if not is_default_team:
        delete_team_form: Any = await TeamDeleteForm.from_formdata(
            request,
            team=team
        )
        if request.method == "POST" and fragment == "danger":
            if await delete_team_form.validate_on_submit():
                try:
                    delete_team_form.status = "deleted"
                    await db.commit()

                    # Team is marked as deleted, actual cleanup is delegated to a job
                    deployment_queue = await get_deployment_queue()
                    await deployment_queue.enqueue_job("cleanup", team.id, job_timeout=300)

                    flash(
                        request,
                        _('Team "%(name)s" has been marked for deletion.')
                        % {"name": team.name},
                        "success",
                    )
                    return RedirectResponse("/")
                except Exception as e:
                    await db.rollback()
                    logger.error(f'Error marking team "{team.name}" as deleted: {str(e)}')
                    flash(
                        request,
                        _("An error occurred while marking the team for deletion."),
                        "error",
                    )

            for error in delete_team_form.confirm.errors:
                flash(request, error, "error")

            return RedirectResponse(
                url=str(request.url_for("team_settings", team_slug=team.slug))
                + "#danger",
                status_code=303,
            )

    # General
    general_form: Any = await TeamGeneralForm.from_formdata(
        request,
        data={
            "name": team.name,
            "slug": team.slug,
        }
    )

    if fragment == "general":
        if request.method == "POST" and await general_form.validate_on_submit():
            # Name
            team.name = general_form.name.data or ""

            # Slug
            old_slug = team.slug
            team.slug = general_form.slug.data or ""

            # Avatar upload
            avatar_file = general_form.avatar.data
            if (
                avatar_file
                and hasattr(avatar_file, "filename")
                and avatar_file.filename
            ):
                try:
                    from PIL import Image

                    avatar_dir = os.path.join(settings.upload_dir, "avatars")
                    os.makedirs(avatar_dir, exist_ok=True)

                    target_filename = f"team_{team.id}.webp"
                    target_filepath = os.path.join(avatar_dir, target_filename)

                    await avatar_file.seek(0)
                    img = Image.open(avatar_file.file)

                    if img.mode != "RGBA":
                        img = img.convert("RGBA")

                    max_size = (512, 512)
                    img.thumbnail(max_size)

                    img.save(target_filepath, "WEBP", quality=85)

                    team.has_avatar = True
                    team.updated_at = utc_now()
                except Exception as e:
                    logger.error(f"Error processing avatar: {str(e)}")
                    flash(request, _("Avatar could not be updated."), "error")

            # Avatar deletion
            if general_form.delete_avatar.data:
                try:
                    avatar_dir = os.path.join(settings.upload_dir, "avatars")
                    filename = f"team_{team.id}.webp"
                    filepath = os.path.join(avatar_dir, filename)

                    if os.path.exists(filepath):
                        os.remove(filepath)

                    team.has_avatar = False
                    team.updated_at = utc_now()
                except Exception as e:
                    logger.error(f"Error deleting avatar: {str(e)}")
                    flash(request, _("Avatar could not be removed."), "error")

            await db.commit()
            flash(request, _("General settings updated."), "success")

            # Redirect if the name has changed
            if old_slug != team.slug:
                new_url = request.url_for("team_settings", team_slug=team.slug)

                if request.headers.get("HX-Request"):
                    return Response(
                        status_code=200, headers={"HX-Redirect": str(new_url)}
                    )
                else:
                    return RedirectResponse(new_url, status_code=303)

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="teams/partials/_settings-general.html",
                context={
                    "current_user": current_user,
                    "general_form": general_form,
                    "team": team,
                },
            )

    # Members
    members = await db.execute(
        select(TeamMember)
        .where(TeamMember.team_id == team.id)
        .options(selectinload(TeamMember.user))
    )
    members = members.scalars().all()

    latest_teams = await get_latest_teams(db=db, current_team=team, limit=5)

    return TemplateResponse(
        request=request,
        name="teams/pages/settings.html",
        context={
            "current_user": current_user,
            "team": team,
            "delete_team_form": delete_team_form,
            "general_form": general_form,
            "members": members,
            "latest_teams": latest_teams,
        },
    )