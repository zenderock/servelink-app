from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import Response, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime
from redis.asyncio import Redis
from arq.connections import ArqRedis
from urllib.parse import urlparse, parse_qs
import logging
import os
from typing import Any

from dependencies import (
    get_current_user,
    get_project_by_name,
    get_deployment_by_id,
    get_team_by_slug,
    get_github_service,
    get_redis_client,
    get_deployment_queue,
    flash,
    get_translation as _,
    TemplateResponse,
    RedirectResponseX,
    get_role,
    get_access,
    get_github_installation_service,
)
from models import (
    Project,
    Deployment,
    User,
    Team,
    TeamMember,
    utc_now,
)
from forms.project import (
    NewProjectForm,
    ProjectDeployForm,
    ProjectDeleteForm,
    ProjectGeneralForm,
    ProjectEnvVarsForm,
    ProjectEnvironmentForm,
    ProjectDeleteEnvironmentForm,
    ProjectBuildAndProjectDeployForm,
    ProjectRollbackForm,
)
from config import get_settings, Settings
from db import get_db
from services.github import GitHubService
from services.github_installation import GitHubInstallationService
from services.deployment import DeploymentService
from utils.project import get_latest_projects, get_latest_deployments
from utils.team import get_latest_teams
from utils.pagination import paginate
from utils.environment import group_branches_by_environment, get_environment_for_branch
from utils.color import COLORS
from utils.user import get_user_github_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{team_slug}/new-project", name="new_project")
async def new_project(
    request: Request,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
):
    team, membership = team_and_membership

    return TemplateResponse(
        request=request,
        name="project/pages/new.html",
        context={
            "current_user": current_user,
            "team": team,
        },
    )


@router.api_route(
    "/{team_slug}/new-project/details",
    methods=["GET", "POST"],
    name="new_project_details",
)
async def new_project_details(
    request: Request,
    repo_id: str = Query(None),
    repo_owner: str = Query(None),
    repo_name: str = Query(None),
    repo_default_branch: str = Query(None),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    github_service: GitHubService = Depends(get_github_service),
    github_installation_service: GitHubInstallationService = Depends(
        get_github_installation_service
    ),
):
    team, membership = team_and_membership

    if not all([repo_id, repo_owner, repo_name, repo_default_branch]):
        flash(request, _("Missing repository details."), "error")
        return RedirectResponse(
            request.url_for("new_project", team_slug=team.slug), status_code=303
        )

    form: Any = await NewProjectForm.from_formdata(request, db=db, team=team)

    if request.method == "GET":
        form.repo_id.data = int(repo_id)
        form.name.data = repo_name
        form.production_branch.data = repo_default_branch

    if request.method == "POST" and await form.validate_on_submit():
        try:
            github_oauth_token = await get_user_github_token(db, current_user)
            if not github_oauth_token:
                raise ValueError("GitHub OAuth token missing.")

            if not form.repo_id.data:
                raise ValueError("Repository ID missing.")

            repo = await github_service.get_repository(
                github_oauth_token, int(form.repo_id.data)
            )
        except Exception:
            flash(request, "You do not have access to this repository.", "error")
            return RedirectResponse(
                request.url_for("new_project", team_slug=team.slug), status_code=303
            )

        installation = await github_service.get_repository_installation(
            repo["full_name"]
        )
        github_installation = (
            await github_installation_service.get_or_refresh_installation(
                installation["id"], db
            )
        )

        env_vars = [
            {
                "key": entry.key.data,
                "value": entry.value.data,
                "environment": entry.environment.data,
            }
            for entry in form.env_vars
        ]

        project = Project(
            name=form.name.data,
            repo_id=form.repo_id.data,
            repo_full_name=repo["full_name"],
            github_installation=github_installation,
            config={
                "framework": form.framework.data,
                "runtime": form.runtime.data,
                "root_directory": form.root_directory.data
                if form.use_custom_root_directory.data
                else None,
                "build_command": form.build_command.data
                if form.use_custom_build_command.data
                else None,
                "pre_deploy_command": form.pre_deploy_command.data
                if form.use_custom_pre_deploy_command.data
                else None,
                "start_command": form.start_command.data
                if form.use_custom_start_command.data
                else None,
            },
            env_vars=env_vars,
            environments=[
                {
                    "id": "prod",
                    "color": "blue",
                    "name": "Production",
                    "slug": "production",
                    "branch": form.production_branch.data,
                    "status": "active",
                }
            ],
            team=team,
            created_by_user_id=current_user.id,
        )

        db.add(project)
        await db.commit()
        flash(request, _("Project added."), "success")

        return RedirectResponseX(
            url=str(
                request.url_for(
                    "project_index", team_slug=team.slug, project_name=project.name
                )
            ),
            request=request,
        )

    return TemplateResponse(
        request=request,
        name="project/partials/_form-new-project.html"
        if request.headers.get("HX-Request")
        else "project/pages/new-details.html",
        context={
            "current_user": current_user,
            "team": team,
            "form": form,
            "repo_full_name": f"{repo_owner or ''}/{repo_name or ''}",
            "frameworks": settings.frameworks,
            "environments": [
                {"color": "blue", "name": "Production", "slug": "production"}
            ],
        },
    )


@router.get("/{team_slug}/projects/{project_name}", name="project_index")
async def project_index(
    request: Request,
    fragment: str | None = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    role: str = Depends(get_role),
):
    team, membership = team_and_membership
    fragment = request.query_params.get("fragment")

    result = await db.execute(
        select(Deployment)
        .options(selectinload(Deployment.aliases))
        .where(Deployment.project_id == project.id)
        .order_by(Deployment.created_at.desc())
        .limit(10)
    )
    deployments = result.scalars().all()

    env_aliases = await project.get_environment_aliases(db=db)

    if request.headers.get("HX-Request") and fragment == "deployments":
        return TemplateResponse(
            request=request,
            name="project/partials/_index-deployments.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployments": deployments,
                "env_aliases": env_aliases,
            },
        )

    latest_teams = await get_latest_teams(
        db=db, current_user=current_user, current_team=team, limit=5
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project, limit=5
    )

    return TemplateResponse(
        request=request,
        name="project/pages/index.html",
        context={
            "current_user": current_user,
            "role": role,
            "team": team,
            "project": project,
            "deployments": deployments,
            "deploy_domain": settings.deploy_domain,
            "env_aliases": env_aliases,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
        },
    )


@router.get(
    "/{team_slug}/projects/{project_name}/deployments", name="project_deployments"
)
async def project_deployments(
    request: Request,
    fragment: str = Query(None),
    environment: str = Query(None),
    status: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None),
    page: int = Query(1, ge=1),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    role: str = Depends(get_role),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    team, membership = team_and_membership
    per_page = 25
    env_aliases = await project.get_environment_aliases(db=db)

    result = await db.execute(
        select(Deployment.branch).where(Deployment.project_id == project.id).distinct()
    )
    branches = [
        {"name": branch, "value": branch} for branch in result.scalars().all() if branch
    ]

    query = (
        select(Deployment)
        .options(selectinload(Deployment.aliases))
        .where(Deployment.project_id == project.id)
        .order_by(Deployment.created_at.desc())
    )

    if request.headers.get("HX-Request") and fragment == "sse":
        # This is for the SSE updates. We get the search params from the
        # referer as the state may have changed via the HTMX filters.
        environment = ""
        status = ""
        date_from = ""
        date_to = ""
        branch = ""
        page = 1

        referer_url = urlparse(request.headers["Referer"])
        referer_params = parse_qs(referer_url.query)

        if "environment" in referer_params:
            environment = referer_params["environment"][0]
        if "status" in referer_params:
            status = referer_params["status"][0]
        if "date_from" in referer_params:
            date_from = referer_params["date_from"][0]
        if "date_to" in referer_params:
            date_to = referer_params["date_to"][0]
        if "branch" in referer_params:
            branch = referer_params["branch"][0]
        if "page" in referer_params:
            page = int(referer_params["page"][0])

    # Filter by environment
    if environment:
        environment_object = project.get_environment_by_slug(environment)
        if environment_object:
            query = query.where(
                Deployment.environment_id == environment_object.get("id")
            )

    # Filter by status (conclusion)
    if status:
        if status == "in_progress":
            query = query.where(Deployment.conclusion.is_(None))
        else:
            query = query.where(Deployment.conclusion == status)

    # Filter by date range# Filter by date range
    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from)
            query = query.where(Deployment.created_at >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to)
            query = query.where(Deployment.created_at <= to_date)
        except ValueError:
            pass

    # Filter by branch
    if branch:
        query = query.where(Deployment.branch == branch)

    pagination = await paginate(db, query, page, per_page)

    if request.headers.get("HX-Request"):
        return TemplateResponse(
            request=request,
            name="project/partials/_deployments.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployments": pagination.get("items"),
                "pagination": pagination,
                "env_aliases": env_aliases,
            },
        )

    latest_teams = await get_latest_teams(
        db=db, current_user=current_user, current_team=team, limit=5
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project, limit=5
    )

    return TemplateResponse(
        request=request,
        name="project/pages/deployments.html",
        context={
            "current_user": current_user,
            "role": role,
            "team": team,
            "project": project,
            "deployments": pagination.get("items"),
            "pagination": pagination,
            "branches": branches,
            "env_aliases": env_aliases,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
        },
    )


@router.api_route(
    "/{team_slug}/projects/{project_name}/deploy",
    methods=["GET", "POST"],
    name="project_deploy",
)
async def project_deploy(
    request: Request,
    environment_id: str = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    github_service: GitHubService = Depends(get_github_service),
    redis_client: Redis = Depends(get_redis_client),
    deployment_queue: ArqRedis = Depends(get_deployment_queue),
    github_installation_service: GitHubInstallationService = Depends(
        get_github_installation_service
    ),
):
    team, membership = team_and_membership

    form: Any = await ProjectDeployForm.from_formdata(request=request)

    if request.method == "POST" and await form.validate_on_submit():
        try:
            branch, commit_sha = form.commit.data.split(":")

            github_installation = (
                await github_installation_service.get_or_refresh_installation(
                    project.github_installation_id, db
                )
            )
            if not github_installation.token:
                raise ValueError("GitHub installation token missing.")

            commit = await github_service.get_repository_commit(
                user_access_token=github_installation.token,
                repo_id=project.repo_id,
                commit_sha=commit_sha,
                branch=branch,
            )

            deployment = await DeploymentService().create_deployment(
                project=project,
                branch=branch,
                commit=commit,
                current_user=current_user,
                db=db,
                redis_client=redis_client,
                deployment_queue=deployment_queue,
            )

            flash(
                request,
                _(
                    "Deployment %(deployment_id)s created.",
                    deployment_id=deployment.id[:7],
                ),
                "success",
            )

            return RedirectResponseX(
                url=str(
                    request.url_for(
                        "project_deployment",
                        team_slug=team.slug,
                        project_name=project.name,
                        deployment_id=deployment.id,
                    )
                ),
                request=request,
            )

        except Exception as e:
            error_message = _("Error deploying %(project)s: %(error)s") % {
                "project": project.name,
                "error": str(e),
            }
            logger.error(error_message)
            flash(request, error_message, "error")

    # Get the list of commits for the selected environment
    branch_names = []
    commits = []
    try:
        github_installation = (
            await github_installation_service.get_or_refresh_installation(
                project.github_installation_id, db
            )
        )
        if not github_installation.token:
            raise ValueError("GitHub installation token missing.")

        branches = await github_service.get_repository_branches(
            github_installation.token, project.repo_id
        )
        branch_names = [branch["name"] for branch in branches]
    except Exception as e:
        logger.error(f"Error fetching branches: {str(e)}")
        flash(request, _("Error fetching branches from GitHub."), "error")

    if len(branch_names) > 0:
        # Find branches that match this environment
        branches_by_environment = group_branches_by_environment(
            project.active_environments, branch_names
        )
        environment = project.get_environment_by_id(environment_id)
        if not environment:
            raise ValueError("Environment not found.")
        matching_branches = branches_by_environment.get(environment["slug"])

        # Get the latest 5 commits for each matching branch
        if matching_branches:
            for branch in matching_branches:
                try:
                    if not github_installation.token:
                        raise ValueError("GitHub installation token missing.")

                    branch_commits = await github_service.get_repository_commits(
                        github_installation.token, project.repo_id, branch, per_page=5
                    )

                    # Add branch information to each commit
                    for commit in branch_commits:
                        commit["branch"] = branch
                        commits.append(commit)
                except Exception as e:
                    warning_message = _(
                        "Could not fetch commits for branch %(branch)s: %(error)s"
                    ) % {"branch": branch, "error": str(e)}
                    logger.warning(warning_message)
                    flash(request, warning_message, "warning")
                    continue

        # Sort commits by date (newest first)
        commits.sort(key=lambda x: x["commit"]["author"]["date"], reverse=True)

    return TemplateResponse(
        request=request,
        name="project/partials/_dialog-deploy-commits.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "form": form,
            "commits": commits,
        },
    )


@router.api_route(
    "/{team_slug}/projects/{project_name}/deplyments/{deployment_id}/rollback",
    methods=["GET", "POST"],
    name="project_redeploy",
)
async def project_redeploy(
    request: Request,
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    deployment: Deployment = Depends(get_deployment_by_id),
    db: AsyncSession = Depends(get_db),
    github_service: GitHubService = Depends(get_github_service),
    redis_client: Redis = Depends(get_redis_client),
    deployment_queue: ArqRedis = Depends(get_deployment_queue),
    github_installation_service: GitHubInstallationService = Depends(
        get_github_installation_service
    ),
):
    team, membership = team_and_membership

    form: Any = await ProjectDeployForm.from_formdata(request)

    environment = get_environment_for_branch(
        deployment.branch, project.active_environments
    )

    if environment and request.method == "POST" and await form.validate_on_submit():
        try:
            github_installation = (
                await github_installation_service.get_or_refresh_installation(
                    project.github_installation_id, db
                )
            )
            if not github_installation.token:
                raise ValueError("GitHub installation token missing.")

            commit = await github_service.get_repository_commit(
                user_access_token=github_installation.token,
                repo_id=project.repo_id,
                commit_sha=deployment.commit_sha,
                branch=deployment.branch,
            )

            new_deployment = await DeploymentService().create_deployment(
                project=project,
                branch=deployment.branch,
                commit=commit,
                current_user=current_user,
                db=db,
                redis_client=redis_client,
                deployment_queue=deployment_queue,
            )

            flash(
                request,
                _(
                    "Deployment %(new_deployment_id)s created.",
                    new_deployment_id=new_deployment.id,
                ),
                "success",
            )

            return RedirectResponseX(
                url=str(
                    request.url_for(
                        "project_deployment",
                        team_slug=team.slug,
                        project_name=project.name,
                        deployment_id=new_deployment.id,
                    )
                ),
                request=request,
            )

        except Exception as e:
            logger.error(f"Error redeploying project: {str(e)}")
            flash(request, _("Error redeploying project."), "error")

    return TemplateResponse(
        request=request,
        name="project/partials/_dialog-redeploy-form.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "form": form,
            "deployment": deployment,
            "environment": environment,
        },
    )


@router.api_route(
    "/{team_slug}/projects/{project_name}/deployments/{deployment_id}/rollback",
    methods=["GET", "POST"],
    name="project_rollback",
)
async def project_rollback(
    request: Request,
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    deployment: Deployment = Depends(get_deployment_by_id),
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_settings),
):
    team, membership = team_and_membership

    form: Any = await ProjectRollbackForm.from_formdata(request)

    if request.method == "POST" and await form.validate_on_submit():
        try:
            environment = project.get_environment_by_id(form.environment_id.data)
            if not environment:
                raise ValueError("Environment not found.")

            await DeploymentService().rollback(
                environment=environment,
                project=project,
                db=db,
                redis_client=redis_client,
                settings=settings,
            )

            flash(
                request,
                _(
                    'Environment "%(environment_id)s" rolled back to deployment %(deployment_id)s.',
                    environment_id=environment["id"],
                    deployment_id=deployment.id,
                ),
                "success",
            )

        except Exception as e:
            logger.error(f"Error rolling back project: {str(e)}")
            flash(request, _("Error rolling back project."), "error")
    else:
        for error in form.errors.values():
            for e in error:
                flash(request, _("Rollback failed: %(error)s", error=e), "error")

    return TemplateResponse(
        request=request,
        name="project/partials/_dialog-rollback-form.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "form": form,
            "deployment": deployment,
        },
    )


# @router.api_route(
#     "/{team_slug}/projects/{project_name}/deployments/{deployment_id}/promote",
#     methods=["GET", "POST"],
#     name="project_promote",
# )
# async def project_promote(
#     request: Request,
#     project: Project = Depends(get_project_by_name),
#     current_user: User = Depends(get_current_user),
#     team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
#     deployment: Deployment = Depends(get_deployment_by_id),
#     db: AsyncSession = Depends(get_db),
#     redis_client: Redis = Depends(get_redis_client),
#     settings: Settings = Depends(get_settings),
# ):
#     team, membership = team_and_membership

#     form: Any = await ProjectRollbackForm.from_formdata(request)

#     if request.method == "POST" and await form.validate_on_submit():
#         try:
#             environment = project.get_environment_by_id(form.environment_id.data)
#             if not environment:
#                 raise ValueError("Environment not found.")

#             deployment = await get_deployment_by_id(form.deployment_id.data, db)

#             await DeploymentService().promote(
#                 environment=environment,
#                 deployment=deployment,
#                 project=project,
#                 db=db,
#                 redis_client=redis_client,
#                 settings=settings,
#             )

#             flash(
#                 request,
#                 _(
#                     'Deployment %(deployment_id)s promoted to "%(environment_id)s".',
#                     deployment_id=deployment.id,
#                     environment_id=environment["id"],
#                 ),
#                 "success",
#             )

#         except Exception as e:
#             logger.error(f"Error rolling back project: {str(e)}")
#             flash(request, _("Error rolling back project."), "error")
#     else:
#         for error in form.errors.values():
#             for e in error:
#                 flash(request, _("Rollback failed: %(error)s", error=e), "error")

#     return TemplateResponse(
#         request=request,
#         name="project/partials/_dialog-rollback-form.html",
#         context={
#             "current_user": current_user,
#             "team": team,
#             "project": project,
#             "form": form,
#             "deployment": deployment,
#         },
#     )


@router.api_route(
    "/{team_slug}/projects/{project_name}/settings",
    methods=["GET", "POST"],
    name="project_settings",
)
async def project_settings(
    request: Request,
    fragment: str = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    role: str = Depends(get_role),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    deployment_queue: ArqRedis = Depends(get_deployment_queue),
):
    team, membership = team_and_membership

    if not get_access(role, "creator"):
        flash(
            request,
            _("You don't have permission to access project settings."),
            "warning",
        )
        return RedirectResponse(
            request.url_for(
                "project_index", team_slug=team.slug, project_name=project.name
            ),
            status_code=302,
        )

    # Delete
    delete_project_form = None
    if get_access(role, "admin"):
        delete_project_form: Any = await ProjectDeleteForm.from_formdata(
            request, project=project
        )
        if request.method == "POST" and fragment == "danger":
            if await delete_project_form.validate_on_submit():
                try:
                    project.status = "deleted"
                    await db.commit()

                    # Project is marked as deleted, actual cleanup is delegated to a job
                    await deployment_queue.enqueue_job("cleanup_project", project.id)

                    flash(
                        request,
                        _('Project "%(name)s" has been marked for deletion.')
                        % {"name": project.name},
                        "success",
                    )
                    return RedirectResponse("/", status_code=303)
                except Exception as e:
                    await db.rollback()
                    logger.error(
                        f"Error marking project {project.name} as deleted: {str(e)}"
                    )
                    flash(
                        request,
                        _("An error occurred while marking the project for deletion."),
                        "error",
                    )

            for error in delete_project_form.confirm.errors:
                flash(request, error, "error")

    # General
    general_form: Any = await ProjectGeneralForm.from_formdata(
        request,
        data={"name": project.name, "repo_id": project.repo_id},
        db=db,
        team=team,
        project=project,
    )

    if fragment == "general":
        if request.method == "POST" and await general_form.validate_on_submit():
            # Name
            old_name = project.name
            project.name = general_form.name.data or ""

            # Repo
            if general_form.repo_id.data != project.repo_id:
                try:
                    github_service = get_github_service()
                    github_oauth_token = await get_user_github_token(db, current_user)
                    repo = await github_service.get_repository(
                        github_oauth_token or "", general_form.repo_id.data
                    )
                except Exception:
                    flash(
                        request,
                        _("You do not have access to this repository."),
                        "error",
                    )
                project.repo_id = general_form.repo_id.data
                project.repo_full_name = repo.get("full_name") or ""

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

                    target_filename = f"project_{project.id}.webp"
                    target_filepath = os.path.join(avatar_dir, target_filename)

                    await avatar_file.seek(0)
                    img = Image.open(avatar_file.file)

                    if img.mode != "RGBA":
                        img = img.convert("RGBA")

                    max_size = (512, 512)
                    img.thumbnail(max_size)

                    img.save(target_filepath, "WEBP", quality=85)

                    project.has_avatar = True
                    project.updated_at = utc_now()
                except Exception as e:
                    logger.error(f"Error processing avatar: {str(e)}")
                    flash(request, _("Avatar could not be updated."), "error")

            # Avatar deletion
            if general_form.delete_avatar.data:
                try:
                    avatar_dir = os.path.join(settings.upload_dir, "avatars")
                    filename = f"project_{project.id}.webp"
                    filepath = os.path.join(avatar_dir, filename)

                    if os.path.exists(filepath):
                        os.remove(filepath)

                    project.has_avatar = False
                    project.updated_at = utc_now()
                except Exception as e:
                    logger.error(f"Error deleting avatar: {str(e)}")
                    flash(request, _("Avatar could not be removed."), "error")

            await db.commit()
            flash(request, _("General settings updated."), "success")

            # Redirect if the name has changed
            if old_name != project.name:
                new_url = request.url_for(
                    "project_settings", team_slug=team.slug, project_name=project.name
                )

                if request.headers.get("HX-Request"):
                    return Response(
                        status_code=200, headers={"HX-Redirect": str(new_url)}
                    )
                else:
                    return RedirectResponse(new_url, status_code=303)

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="project/partials/_settings-general.html",
                context={
                    "current_user": current_user,
                    "team": team,
                    "general_form": general_form,
                    "project": project,
                },
            )

    # Environment variables
    env_vars_form: Any = await ProjectEnvVarsForm.from_formdata(
        request,
        data={
            "env_vars": [
                {
                    "key": env.get("key", ""),
                    "value": env.get("value", ""),
                    "environment": env.get("environment", ""),
                }
                for env in project.env_vars
            ]
        },
    )

    environment_choices = [("", _("All environments"))]
    for env in project.environments:
        environment_choices.append((env["slug"], env["name"]))

    for env_var_form in env_vars_form.env_vars:
        setattr(env_var_form.environment, "choices", environment_choices)

    if fragment == "env_vars":
        if await env_vars_form.validate_on_submit():
            project.env_vars = [
                {
                    "key": entry.key.data,
                    "value": entry.value.data,
                    "environment": entry.environment.data,
                }
                for entry in env_vars_form.env_vars
            ]
            await db.commit()
            flash(request, _("Environment variables updated."), "success")

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="project/partials/_settings-env-vars.html",
                context={
                    "current_user": current_user,
                    "team": team,
                    "env_vars_form": env_vars_form,
                    "project": project,
                },
            )

    # Environments
    environment_form: Any = await ProjectEnvironmentForm.from_formdata(
        request=request, project=project
    )
    delete_environment_form: Any = await ProjectDeleteEnvironmentForm.from_formdata(
        request=request, project=project
    )
    environments_updated = False

    if fragment == "environment":
        if await environment_form.validate_on_submit():
            try:
                if environment_form.environment_id.data:
                    # Update existing environment using ID
                    environment_id = environment_form.environment_id.data
                    env = project.get_environment_by_id(environment_id)

                    if env:
                        values = {
                            "color": environment_form.color.data,
                            "name": environment_form.name.data,
                            "slug": environment_form.slug.data,
                            "branch": environment_form.branch.data,
                        }

                        project.update_environment(environment_id, values)
                        await db.commit()
                        flash(request, _("Environment updated."), "success")
                        environments_updated = True
                    else:
                        flash(request, _("Environment not found."), "error")
                else:
                    # Create new environment
                    if env := project.create_environment(
                        name=environment_form.name.data or "",
                        slug=environment_form.slug.data or "",
                        color=environment_form.color.data or "",
                        branch=environment_form.branch.data or "",
                    ):
                        await db.commit()
                        flash(request, _("Environment added."), "success")
                        environments_updated = True
                    else:
                        flash(request, _("Failed to create environment."), "error")
            except ValueError as e:
                logger.error(f"Error creating environment: {str(e)}")
                flash(request, _("Something went wrong. Please try again."), "error")

    if fragment == "delete_environment":
        if await delete_environment_form.validate_on_submit():
            try:
                if project.delete_environment(
                    delete_environment_form.environment_id.data
                ):
                    await db.commit()
                    flash(request, _("Environment deleted."), "success")
                    environments_updated = True
                else:
                    flash(request, _("Environment not found."), "error")
            except ValueError as e:
                logger.error(f"Error deleting environment: {str(e)}")
                flash(request, _("Something went wrong. Please try again."), "error")

    if fragment in ("environment", "delete_environment") and request.headers.get(
        "HX-Request"
    ):
        return TemplateResponse(
            request=request,
            name="project/partials/_settings-environments.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "environment_form": environment_form,
                "delete_environment_form": delete_environment_form,
                "colors": COLORS,
                "updated": environments_updated,
            },
        )

    # Build and deploy
    build_and_deploy_form: Any = await ProjectBuildAndProjectDeployForm.from_formdata(
        request,
        data={
            "framework": project.config.get("framework"),
            "runtime": project.config.get("runtime"),
            "use_custom_root_directory": project.config.get("root_directory")
            is not None,
            "root_directory": project.config.get("root_directory"),
            "use_custom_build_command": project.config.get("build_command") is not None,
            "build_command": project.config.get("build_command"),
            "use_custom_pre_deploy_command": project.config.get("pre_deploy_command")
            is not None,
            "pre_deploy_command": project.config.get("pre_deploy_command"),
            "use_custom_start_command": project.config.get("start_command") is not None,
            "start_command": project.config.get("start_command"),
        },
    )

    if fragment == "build_and_deploy":
        if await build_and_deploy_form.validate_on_submit():
            project.config = {
                "framework": build_and_deploy_form.framework.data,
                "runtime": build_and_deploy_form.runtime.data,
                "root_directory": build_and_deploy_form.root_directory.data,
                "build_command": build_and_deploy_form.build_command.data
                if build_and_deploy_form.use_custom_build_command.data
                else None,
                "pre_deploy_command": build_and_deploy_form.pre_deploy_command.data
                if build_and_deploy_form.use_custom_pre_deploy_command.data
                else None,
                "start_command": build_and_deploy_form.start_command.data
                if build_and_deploy_form.use_custom_start_command.data
                else None,
            }
            await db.commit()
            flash(request, _("Build & Deploy settings updated."), "success")

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="project/partials/_settings-build-and-deploy.html",
                context={
                    "current_user": current_user,
                    "team": team,
                    "project": project,
                    "build_and_deploy_form": build_and_deploy_form,
                    "frameworks": settings.frameworks,
                },
            )

    return TemplateResponse(
        request=request,
        name="project/pages/settings.html",
        context={
            "current_user": current_user,
            "role": role,
            "team": team,
            "project": project,
            "general_form": general_form,
            "environment_form": environment_form,
            "delete_environment_form": delete_environment_form,
            "build_and_deploy_form": build_and_deploy_form,
            "env_vars_form": env_vars_form,
            "delete_project_form": delete_project_form,
            "colors": COLORS,
            "frameworks": settings.frameworks,
        },
    )


@router.get(
    "/{team_slug}/projects/{project_name}/deployments/{deployment_id}",
    name="project_deployment",
)
async def project_deployment(
    request: Request,
    deployment_id: str,
    fragment: str = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    role: str = Depends(get_role),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    deployment: Deployment = Depends(get_deployment_by_id),
):
    team, membership = team_and_membership

    env_aliases = await project.get_environment_aliases(db=db)

    if request.headers.get("HX-Request") and fragment == "header":
        return TemplateResponse(
            request=request,
            name="deployment/partials/_header.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployment": deployment,
                "env_aliases": env_aliases,
            },
        )

    latest_teams = await get_latest_teams(
        db=db, current_user=current_user, current_team=team, limit=5
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project, limit=5
    )
    latest_deployments = await get_latest_deployments(
        db=db, project=project, current_deployment=deployment, limit=5
    )

    return TemplateResponse(
        request=request,
        name="deployment/pages/index.html",
        context={
            "current_user": current_user,
            "role": role,
            "team": team,
            "project": project,
            "deployment": deployment,
            "env_aliases": env_aliases,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
            "latest_deployments": latest_deployments,
        },
    )
