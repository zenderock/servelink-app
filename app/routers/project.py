from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import Response, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, timezone
from redis.asyncio import Redis
from arq.connections import ArqRedis
from urllib.parse import urlparse, parse_qs
import logging
import os
import json
from pathlib import Path
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
    get_pricing_service,
)
from services.pricing import PricingService
from models import (
    Project,
    Deployment,
    Domain,
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
    ProjectCancelDeploymentForm,
    ProjectRollbackDeploymentForm,
    ProjectDomainForm,
    ProjectRemoveDomainForm,
    ProjectVerifyDomainForm,
    ProjectResourcesForm,
)
from config import get_settings, Settings
from db import get_db
from services.github import GitHubService
from services.github_installation import GitHubInstallationService
from services.deployment import DeploymentService
from services.domain import DomainService
from services.project_monitoring import ProjectMonitoringService
from utils.project import get_latest_projects, get_latest_deployments
from utils.team import get_latest_teams
from utils.pagination import paginate
from utils.environment import group_branches_by_environment, get_environment_for_branch
from utils.color import COLORS
from utils.user import get_user_github_token
from utils.project import generate_unique_project_name

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_PROJECT_PRESETS = [
    {
        "id": "go-starter",
        "title": "Go CRUD Starter - API REST",
        "description": "API REST Go professionnelle avec Gin framework, architecture propre et performances optimales.",
        "github_url": "https://github.com/servelink-deploy/go-crud-starter",
        "doc_url": "https://github.com/servelink-deploy/go-crud-starter",
        "tags": ["Go", "Gin", "PostgreSQL"],
        "icon": "go"
    },
    {
        "id": "django-starter",
        "title": "Django CRUD Starter - API REST",
        "description": "Application Django professionnelle avec Django REST Framework, ViewSets, pagination automatique et documentation Swagger.",
        "github_url": "https://github.com/servelink-deploy/django-crud-starter",
        "doc_url": "https://github.com/servelink-deploy/django-crud-starter",
        "tags": ["Python", "Django", "Django REST Framework", "PostgreSQL"],
        "icon": "python"
    },
    {
        "id": "flask-starter",
        "title": "Flask CRUD Starter - API REST",
        "description": "Application Flask professionnelle avec Flask RESTful, ViewSets, pagination automatique et documentation Swagger.",
        "github_url": "https://github.com/servelink-deploy/flask-crud-starter",
        "doc_url": "https://github.com/servelink-deploy/flask-crud-starter",
        "tags": ["Python", "Flask", "Flask RESTful", "PostgreSQL"],
        "icon": "python"
    },
    {
        "id": "nodejs-starter",
        "title": "Node.js Starter - API REST",
        "description": "Application Node.js professionnelle avec Express, ViewSets, pagination automatique et documentation Swagger.",
        "github_url": "https://github.com/servelink-deploy/nodejs-crud-starter",
        "doc_url": "https://github.com/servelink-deploy/nodejs-crud-starter",
        "tags": ["Node.js", "Express", "PostgreSQL"],
        "icon": "nodejs"
    }
]


@router.get("/{team_slug}/new-project", name="new_project")
async def new_project(
    request: Request,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    pricing_service: PricingService = Depends(get_pricing_service),
):
    team, membership = team_and_membership

    can_create, error_message = await pricing_service.validate_project_creation(team, db)

    project_presets = DEFAULT_PROJECT_PRESETS
    try:
        presets_path = Path(__file__).parent.parent / "data" / "project_presets.json"
        if presets_path.exists():
            with open(presets_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                loaded_presets = data.get("presets", [])
                if loaded_presets:
                    project_presets = loaded_presets
    except Exception as e:
        logging.error(f"Error loading project presets, using default: {e}")

    return TemplateResponse(
        request=request,
        name="project/pages/new.html",
        context={
            "current_user": current_user,
            "team": team,
            "can_create_project": can_create,
            "project_creation_error": error_message,
            "project_presets": project_presets,
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
        # Validate project creation limits
        pricing_service = get_pricing_service()
        can_create, error_message = await pricing_service.validate_project_creation(team, db)
        if not can_create:
            flash(request, error_message, "error")
            return TemplateResponse(
                request=request,
                name="project/pages/new-project-details.html",
                context={
                    "form": form,
                    "team": team,
                    "repo": {
                        "id": repo_id,
                        "owner": repo_owner,
                        "name": repo_name,
                        "default_branch": repo_default_branch,
                    },
                },
            )
        
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

        # Generate unique project name
        unique_name = await generate_unique_project_name(db, team, form.name.data)
        
        project = Project(
            name=unique_name,
            repo_id=form.repo_id.data,
            repo_full_name=repo["full_name"],
            github_installation=github_installation,
            config={
                "preset": form.preset.data,
                "image": form.image.data,
                "root_directory": form.root_directory.data,
                "build_command": form.build_command.data,
                "pre_deploy_command": form.pre_deploy_command.data,
                "start_command": form.start_command.data,
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
        
        # Inform user if name was changed
        if unique_name != form.name.data:
            flash(request, _("Project added as '{name}' (original name was already taken).").format(name=unique_name), "info")
        else:
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
        if request.headers.get("HX-Request") and request.method == "POST"
        else "project/pages/new-details.html",
        context={
            "current_user": current_user,
            "team": team,
            "form": form,
            "repo_full_name": f"{repo_owner or ''}/{repo_name or ''}",
            "presets": settings.presets,
            "images": settings.images,
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
        db=db, current_user=current_user, current_team=team
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project
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

    if request.headers.get("HX-Request") and fragment == "deployments":
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
        db=db, current_user=current_user, current_team=team
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project
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

            deployment = await DeploymentService().create(
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
    "/{team_slug}/projects/{project_name}/deployments/{deployment_id}/redeploy",
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

            new_deployment = await DeploymentService().create(
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
    "/{team_slug}/projects/{project_name}/deployments/{deployment_id}/cancel",
    methods=["GET", "POST"],
    name="project_cancel",
)
async def project_cancel(
    request: Request,
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    deployment: Deployment = Depends(get_deployment_by_id),
    redis_client: Redis = Depends(get_redis_client),
    deployment_queue: ArqRedis = Depends(get_deployment_queue),
):
    team, membership = team_and_membership

    form: Any = await ProjectCancelDeploymentForm.from_formdata(request)

    if request.method == "POST" and await form.validate_on_submit():
        try:
            await DeploymentService().cancel(
                project=project,
                deployment=deployment,
                deployment_queue=deployment_queue,
                redis_client=redis_client,
            )

            flash(
                request,
                _(
                    'Deployment "%(deployment_id)s" canceled.',
                    deployment_id=deployment.id,
                ),
                "success",
            )

        except Exception as e:
            logger.error(f"Error canceling deployment: {str(e)}")
            flash(
                request,
                _(
                    "Error canceling deployment %(deployment_id)s.",
                    deployment_id=deployment.id,
                ),
                "error",
            )

    return TemplateResponse(
        request=request,
        name="project/partials/_dialog-cancel-form.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "form": form,
            "deployment": deployment,
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

    form: Any = await ProjectRollbackDeploymentForm.from_formdata(request)

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

#     form: Any = await ProjectRollbackDeploymentForm.from_formdata(request)

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
                    return RedirectResponseX("/", status_code=303)
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
                    environment_id = environment_form.environment_id.data
                    env = project.get_environment_by_id(environment_id)
                    if not env:
                        raise ValueError(_("Environment not found."))

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
                        raise ValueError(_("Failed to create environment."))
            except ValueError as e:
                await db.rollback()
                logger.error(f"Error editing environments: {str(e)}")
                flash(request, _("Something went wrong. Please try again."), "error")

    if fragment == "delete_environment":
        if await delete_environment_form.validate_on_submit():
            try:
                environment_id = delete_environment_form.environment_id.data
                if project.delete_environment(environment_id):
                    domains_result = await db.execute(
                        select(Domain).where(
                            Domain.project_id == project.id,
                            Domain.environment_id == environment_id,
                            Domain.status == "active",
                        )
                    )
                    domains_to_disable = domains_result.scalars().all()

                    domains_disabled = False
                    for domain in domains_to_disable:
                        domain.status = "disabled"
                        domain.message = f"Environment {environment_id} was deleted"
                        domain.environment_id = None
                        domains_disabled = True

                    await db.commit()
                    flash(request, _("Environment deleted."), "success")
                    environments_updated = True

                    if domains_disabled:
                        deployment_service = DeploymentService()
                        await deployment_service.update_traefik_config(
                            project, db, settings
                        )
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
            "preset": project.config.get("preset"),
            "image": project.config.get("image"),
            "root_directory": project.config.get("root_directory"),
            "build_command": project.config.get("build_command"),
            "pre_deploy_command": project.config.get("pre_deploy_command"),
            "start_command": project.config.get("start_command"),
        },
    )

    preset_choices = []
    for preset in settings.presets:
        preset_choices.append((preset["slug"], preset["name"]))

    build_and_deploy_form.preset.choices = preset_choices

    if fragment == "build_and_deploy":
        if await build_and_deploy_form.validate_on_submit():
            project.config = {
                **project.config,
                "preset": build_and_deploy_form.preset.data,
                "image": build_and_deploy_form.image.data,
                "root_directory": build_and_deploy_form.root_directory.data,
                "build_command": build_and_deploy_form.build_command.data,
                "pre_deploy_command": build_and_deploy_form.pre_deploy_command.data,
                "start_command": build_and_deploy_form.start_command.data,
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
                    "presets": settings.presets,
                    "images": settings.images,
                },
            )

    # Resources
    resources_form: Any = await ProjectResourcesForm.from_formdata(
        request=request,
        project=project,
        data={
            "cpus": project.config.get("cpus") or None,
            "memory": project.config.get("memory") or None,
        },
    )

    if fragment == "resources":
        if await resources_form.validate_on_submit():
            # Validation custom selon plan
            from services.pricing import ResourceValidationService
            valid, error_msg = await ResourceValidationService.validate_resources(
                team, 
                resources_form.cpus.data, 
                resources_form.memory.data,
                db,
                project.id
            )
            
            if not valid:
                flash(request, error_msg, "error")
            else:
                # Mise à jour config ET colonnes
                cpu_value = float(resources_form.cpus.data) if resources_form.cpus.data else None
                memory_value = resources_form.memory.data
                
                project.config = {
                    **project.config,
                    "cpus": cpu_value,
                    "memory": memory_value,
                }
                project.allocated_cpu_cores = cpu_value
                project.allocated_memory_mb = memory_value
                
                await db.commit()
                flash(request, _("Resources updated."), "success")

        if request.headers.get("HX-Request"):
            # Calculer mémoire disponible pour Pay as You Go
            available_memory = None
            if team.current_plan and team.current_plan.name == "pay_as_you_go":
                from services.pricing import ResourceValidationService
                available_memory = await ResourceValidationService.get_available_memory(team, db)
            
            return TemplateResponse(
                request=request,
                name="project/partials/_settings-resources.html",
                context={
                    "current_user": current_user,
                    "team": team,
                    "project": project,
                    "resources_form": resources_form,
                    "default_cpus": settings.default_cpus,
                    "default_memory": settings.default_memory_mb,
                    "available_memory": available_memory,
                },
            )

    # Domains
    domains = await db.execute(select(Domain).where(Domain.project_id == project.id))
    domains = domains.scalars().all()
    domains_changed = False

    domain_form: Any = await ProjectDomainForm.from_formdata(
        request=request, project=project, domains=domains, db=db
    )
    remove_domain_form: Any = await ProjectRemoveDomainForm.from_formdata(
        request=request, project=project, domains=domains
    )
    verify_domain_form: Any = await ProjectVerifyDomainForm.from_formdata(
        request=request, domains=domains
    )

    if fragment == "domain":
        if await domain_form.validate_on_submit():
            # Validate custom domain limits (only for new domains)
            if not domain_form.domain_id.data:
                pricing_service = get_pricing_service()
                can_add, error_message = await pricing_service.validate_custom_domain(team, db)
                if not can_add:
                    flash(request, error_message, "error")
                    return TemplateResponse(
                        request=request,
                        name="project/partials/_settings-domains.html",
                        context={
                            "project": project,
                            "domains": domains,
                            "domain_form": domain_form,
                            "remove_domain_form": remove_domain_form,
                            "verify_domain_form": verify_domain_form,
                            "server_ip": settings.server_ip,
                            "deploy_domain": settings.deploy_domain,
                        },
                    )
            
            try:
                if domain_form.domain_id.data:
                    domain = await project.get_domain_by_id(
                        db, int(domain_form.domain_id.data)
                    )
                    if not domain:
                        raise ValueError(_("Domain not found."))

                    submitted_hostname = domain_form.hostname.data.lower()
                    if domain.hostname != submitted_hostname:
                        domain.hostname = submitted_hostname
                        domain.status = "pending"
                        domain.message = None
                        domain.last_checked_at = None

                    domain.environment_id = domain_form.environment_id.data

                    await db.commit()
                    flash(request, _("Domain updated."), "success")
                else:
                    domain = Domain(
                        hostname=domain_form.hostname.data.lower(),
                        type=domain_form.type.data,
                        environment_id=domain_form.environment_id.data,
                        project_id=project.id,
                        status="pending",
                    )
                    db.add(domain)
                    await db.commit()
                    flash(request, _("Domain added."), "success")
                    domains.append(domain)
            except ValueError as e:
                await db.rollback()
                logger.error(f"Error editing domains: {str(e)}")
                flash(request, _("Something went wrong. Please try again."), "error")

    if fragment == "remove_domain":
        if await remove_domain_form.validate_on_submit():
            try:
                domain = next(
                    (
                        domain
                        for domain in domains
                        if domain.id == int(remove_domain_form.domain_id.data)
                    ),
                    None,
                )
                if not domain:
                    raise ValueError(_("Domain not found."))
                await db.delete(domain)
                await db.commit()
                flash(request, _("Domain removed."), "success")
                domains.remove(domain)

                domains_changed = True
            except ValueError as e:
                logger.error(f"Error removing domain: {str(e)}")
                flash(request, _("Something went wrong. Please try again."), "error")

    if fragment == "verify_domain":
        if await verify_domain_form.validate_on_submit():
            domain = next(
                (
                    domain
                    for domain in domains
                    if domain.id == int(verify_domain_form.domain_id.data)
                ),
                None,
            )
            if not domain:
                raise ValueError(_("Domain not found."))

            verified, message, details = await DomainService(settings).verify_domain(
                hostname=domain.hostname,
                project_id=project.id,
            )
            if verified:
                domain.status = "active"
                domain.last_checked_at = utc_now()
                domain.message = None

                await db.execute(
                    update(Domain)
                    .where(
                        Domain.hostname == domain.hostname,
                        Domain.id != domain.id,
                        Domain.status.in_(["pending", "active", "failed"]),
                    )
                    .values(
                        status="disabled",
                        message="Another domain was verified for this hostname",
                        last_checked_at=utc_now(),
                    )
                )

                flash(
                    request,
                    title=_("Domain verified."),
                    category="success",
                    description=details,
                )

                domains_changed = True
            else:
                domain.status = "failed"
                domain.last_checked_at = utc_now()
                domain.message = details

                flash(
                    request,
                    title=message,
                    category="error",
                    description=details,
                )

            await db.commit()
        else:
            logger.error(f"Error verifying domain: {verify_domain_form.errors}")

    if domains_changed:
        try:
            deployment_service = DeploymentService()
            await deployment_service.update_traefik_config(project, db, settings)
        except Exception as e:
            logger.error(f"Failed to update Traefik config: {e}")
            flash(
                request,
                _("Traefik config update failed."),
                "warning",
            )

    for domain in domains:
        domain.is_apex = len(domain.hostname.split(".")) == 2

    domains.sort(key=lambda x: x.hostname)

    if fragment in ("domain", "remove_domain", "verify_domain") and request.headers.get(
        "HX-Request"
    ):
        return TemplateResponse(
            request=request,
            name="project/partials/_settings-domains.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "domains": domains,
                "domain_form": domain_form,
                "remove_domain_form": remove_domain_form,
                "verify_domain_form": verify_domain_form,
                "server_ip": settings.server_ip,
                "deploy_domain": settings.deploy_domain,
            },
        )

    latest_teams = await get_latest_teams(
        db=db, current_user=current_user, current_team=team
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project
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
            "resources_form": resources_form,
            "default_cpus": settings.default_cpus,
            "default_memory": settings.default_memory_mb,
            "env_vars_form": env_vars_form,
            "delete_project_form": delete_project_form,
            "domain_form": domain_form,
            "remove_domain_form": remove_domain_form,
            "verify_domain_form": verify_domain_form,
            "domains": domains,
            "server_ip": settings.server_ip,
            "deploy_domain": settings.deploy_domain,
            "colors": COLORS,
            "presets": settings.presets,
            "images": settings.images,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
        },
    )


@router.api_route(
    "/{team_slug}/projects/{project_name}/deployments/{deployment_id}",
    methods=["GET", "POST"],
    name="project_deployment",
)
async def project_deployment(
    request: Request,
    fragment: str = Query(None),
    end_timestamp: int | None = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    role: str = Depends(get_role),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    deployment: Deployment = Depends(get_deployment_by_id),
):
    team, membership = team_and_membership

    cancel_form = None
    if not deployment.conclusion:
        cancel_form: Any = await ProjectCancelDeploymentForm.from_formdata(request)

    env_aliases = await project.get_environment_aliases(db=db)

    if request.headers.get("HX-Request") and fragment == "header":
        if request.method == "POST" and await cancel_form.validate_on_submit():
            deployment_queue = get_deployment_queue(request)
            redis_client = get_redis_client()

            try:
                await DeploymentService().cancel(
                    project=project,
                    deployment=deployment,
                    deployment_queue=deployment_queue,
                    redis_client=redis_client,
                    db=db,
                )

                flash(
                    request,
                    _(
                        'Deployment "%(deployment_id)s" canceled.',
                        deployment_id=deployment.id,
                    ),
                    "success",
                )

            except Exception as e:
                logger.error(f"Error canceling deployment: {str(e)}")
                flash(
                    request,
                    _(
                        "Error canceling deployment %(deployment_id)s.",
                        deployment_id=deployment.id,
                    ),
                    "error",
                )

        return TemplateResponse(
            request=request,
            name="deployment/partials/_header.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployment": deployment,
                "env_aliases": env_aliases,
                "cancel_form": cancel_form,
            },
        )

    if request.headers.get("HX-Request") and (
        fragment == "logs" or fragment == "logs-next"
    ):
        logs = []
        limit = 50
        try:
            start_timestamp = None
            if fragment == "logs":
                start_timestamp = (
                    int(
                        deployment.created_at.replace(tzinfo=timezone.utc).timestamp()
                        * 1e9
                    )
                    if deployment.created_at
                    else None
                )
            logs = await request.app.state.loki_service.get_logs(
                limit=limit,
                project_id=project.id,
                deployment_id=deployment.id,
                end_timestamp=end_timestamp,
                start_timestamp=start_timestamp,
                timeout=10.0,
            )
        except Exception as e:
            logger.error(f"Failed to retrieve logs: {e}")
            flash(request, _("Failed to retrieve logs."), "error")

        next_batch_url = None
        if logs and len(logs) == limit:
            next_batch_end_timestamp = int(logs[0]["timestamp"]) - 1
            next_batch_url = request.url.include_query_params(
                end_timestamp=next_batch_end_timestamp,
                fragment="logs-next",
            )

        sse_connect_url = None
        if fragment == "logs" and (
            deployment.status != "completed"
            or deployment.container_status == "running"
            or (
                deployment.concluded_at
                and (utc_now() - deployment.concluded_at).total_seconds() < 5
            )
        ):
            sse_connect_url = request.url_for(
                "deployment_event",
                team_id=team.id,
                project_id=project.id,
                deployment_id=deployment.id,
            )
            if logs:
                sse_start_timestamp = int(logs[-1]["timestamp"]) + 1
                sse_connect_url = sse_connect_url.include_query_params(
                    start_timestamp=sse_start_timestamp
                )

        return TemplateResponse(
            request=request,
            name="deployment/partials/_logs-batch.html",
            context={
                "logs": logs,
                "next_batch_url": next_batch_url,
                "fragment": fragment,
                "team": team,
                "project": project,
                "deployment": deployment,
                "sse_connect_url": sse_connect_url,
            },
        )

    latest_teams = await get_latest_teams(
        db=db, current_user=current_user, current_team=team
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project
    )
    latest_deployments = await get_latest_deployments(
        db=db, project=project, current_deployment=deployment
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
            "cancel_form": cancel_form,
        },
    )


@router.get(
    "/{team_slug}/projects/{project_name}/logs",
    name="project_logs",
)
async def project_logs(
    request: Request,
    fragment: str | None = Query(None),
    deployment_id: str | None = Query(None),
    environment_id: str | None = Query(None),
    branch: str | None = Query(None),
    keyword: str | None = Query(None),
    date_from: str | None = Query(None),
    time_from: str | None = Query(None),
    date_to: str | None = Query(None),
    time_to: str | None = Query(None),
    start_timestamp: int | None = Query(None),
    end_timestamp: int | None = Query(None),
    timezone_offset: int | None = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    role: str = Depends(get_role),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    team, membership = team_and_membership

    deployment = None
    if deployment_id:
        deployment = await db.execute(
            select(Deployment).where(Deployment.id == deployment_id)
        )
        deployment = deployment.scalar_one_or_none()
        if not deployment:
            flash(request, _("Deployment not found."), "error")
            return RedirectResponseX(
                url=str(request.url.include_query_params(deployment_id="")),
                request=request,
            )

    if (date_from and date_to and date_from > date_to) or (
        date_from == date_to and time_from and time_to and time_from > time_to
    ):
        return RedirectResponseX(
            url=str(
                request.url.include_query_params(
                    **(
                        {"date-to": date_from}
                        if date_from > date_to
                        else {"time-to": time_from}
                    )
                )
            ),
            request=request,
        )

    if request.headers.get("HX-Request") and (
        fragment == "logs" or fragment == "logs-next"
    ):
        if not end_timestamp:
            if date_to:
                if time_to:
                    date_dt = datetime.strptime(date_to, "%Y-%m-%d")
                    time_dt = datetime.strptime(time_to, "%H:%M").time()
                    local_dt = datetime.combine(date_dt, time_dt)
                    if timezone_offset is not None:
                        utc_dt = local_dt - timedelta(minutes=timezone_offset)
                    else:
                        utc_dt = local_dt
                    end_timestamp = int(utc_dt.timestamp() * 1e9)
                else:
                    date_dt = datetime.strptime(date_to, "%Y-%m-%d")
                    time_dt = datetime.strptime("23:59:59", "%H:%M:%S").time()
                    local_dt = datetime.combine(date_dt, time_dt)
                    if timezone_offset is not None:
                        utc_dt = local_dt - timedelta(minutes=timezone_offset)
                    else:
                        utc_dt = local_dt
                    end_timestamp = int(utc_dt.timestamp() * 1e9)

        if not start_timestamp:
            if date_from:
                if time_from:
                    date_dt = datetime.strptime(date_from, "%Y-%m-%d")
                    time_dt = datetime.strptime(time_from, "%H:%M").time()
                    local_dt = datetime.combine(date_dt, time_dt)
                    if timezone_offset is not None:
                        utc_dt = local_dt - timedelta(minutes=timezone_offset)
                    else:
                        utc_dt = local_dt
                    start_timestamp = int(utc_dt.timestamp() * 1e9)
                else:
                    date_dt = datetime.strptime(date_from, "%Y-%m-%d")
                    time_dt = datetime.strptime("00:00:00", "%H:%M:%S").time()
                    local_dt = datetime.combine(date_dt, time_dt)
                    if timezone_offset is not None:
                        utc_dt = local_dt - timedelta(minutes=timezone_offset)
                    else:
                        utc_dt = local_dt
                    start_timestamp = int(utc_dt.timestamp() * 1e9)

        if start_timestamp and not end_timestamp:
            end_timestamp = int(datetime.now(timezone.utc).timestamp() * 1e9)

        if not start_timestamp and not end_timestamp:
            result = await db.execute(
                select(Deployment.created_at)
                .where(Deployment.project_id == project.id)
                .order_by(Deployment.created_at.desc())
                .limit(10)
            )
            rows = result.scalars().all()
            if rows:
                oldest_deployment = rows[-1]
                start_timestamp = int(
                    oldest_deployment.replace(tzinfo=timezone.utc).timestamp() * 1e9
                )
                end_timestamp = int(datetime.now(timezone.utc).timestamp() * 1e9)

        limit = 50
        logs = []
        try:
            logs = await request.app.state.loki_service.get_logs(
                project_id=project.id,
                limit=limit,
                start_timestamp=str(start_timestamp) if start_timestamp else None,
                end_timestamp=str(end_timestamp) if end_timestamp else None,
                deployment_id=deployment_id,
                environment_id=environment_id,
                branch=branch,
                keyword=keyword,
                timeout=10.0,
            )
        except Exception as e:
            logger.error(f"Failed to retrieve logs: {e}")
            flash(request, _("Failed to retrieve logs."), "error")

        next_batch_url = None
        if logs and len(logs) == limit:
            next_batch_end_timestamp = int(logs[0]["timestamp"]) - 1
            next_batch_url = request.url.include_query_params(
                end_timestamp=next_batch_end_timestamp,
                fragment="logs-next",
            )

        return TemplateResponse(
            request=request,
            name="project/partials/_logs-batch.html",
            context={
                "team": team,
                "project": project,
                "logs": logs,
                "next_batch_url": next_batch_url,
                "date_from": date_from or "",
                "time_from": time_from or "",
                "date_to": date_to or "",
                "time_to": time_to or "",
                "deployment_id": deployment_id or "",
                "environment_id": environment_id or "",
                "branch": branch,
                "keyword": keyword or "",
                "fragment": fragment,
            },
        )

    result = await db.execute(
        select(Deployment.branch).where(Deployment.project_id == project.id).distinct()
    )
    branches = [
        {"name": branch, "value": branch} for branch in result.scalars().all() if branch
    ]

    deployments = await get_latest_deployments(
        db=db,
        project=project,
        current_deployment=deployment,
        limit=4 if deployment else 5,
    )

    if deployment_id:
        deployments.insert(0, deployment)

    latest_teams = await get_latest_teams(
        db=db, current_user=current_user, current_team=team
    )
    latest_projects = await get_latest_projects(
        db=db, team=team, current_project=project
    )

    return TemplateResponse(
        request=request,
        name="project/pages/logs.html",
        context={
            "current_user": current_user,
            "role": role,
            "team": team,
            "project": project,
            "date_from": date_from or "",
            "time_from": time_from or "",
            "date_to": date_to or "",
            "time_to": time_to or "",
            "deployment_id": deployment_id or "",
            "environment_id": environment_id or "",
            "branch": branch or "",
            "keyword": keyword or "",
            "branches": branches,
            "deployments": deployments,
            "fragment": fragment,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
        },
    )


@router.post(
    "/{team_slug}/projects/{project_name}/reactivate",
    name="project_reactivate",
)
async def project_reactivate(
    request: Request,
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Réactiver un projet inactif"""
    team, membership = team_and_membership
    
    # Vérifier que l'utilisateur a les permissions
    if membership.role not in ["owner", "admin"]:
        flash(request, _("You don't have permission to reactivate this project."), "error")
        return RedirectResponseX(
            url=request.url_for("project_index", team_slug=team.slug, project_name=project.name),
            status_code=303
        )
    
    # Vérifier que le projet peut être réactivé
    if not project.can_be_reactivated():
        flash(request, _("This project cannot be reactivated."), "error")
        return RedirectResponseX(
            url=request.url_for("project_index", team_slug=team.slug, project_name=project.name),
            status_code=303
        )
    
    try:
        # Réactiver le projet
        success = await ProjectMonitoringService.reactivate_project(project, db)
        
        if success:
            # Mettre à jour la configuration Traefik
            deployment_service = DeploymentService()
            await deployment_service.update_traefik_config(project, db, settings)
            
            flash(request, _("Project reactivated successfully!"), "success")
        else:
            flash(request, _("Failed to reactivate project."), "error")
    except Exception as e:
        logger.error(f"Error reactivating project {project.id}: {e}")
        flash(request, _("An error occurred while reactivating the project."), "error")
    
    return RedirectResponseX(
        url=request.url_for("project_index", team_slug=team.slug, project_name=project.name),
        status_code=303
    )
