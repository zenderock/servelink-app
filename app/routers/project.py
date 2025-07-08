from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from redis.asyncio import Redis
from arq.connections import ArqRedis
import logging
import os
from typing import Any

from dependencies import (
    get_current_user,
    get_project_by_name,
    get_deployment_by_id,
    get_team_by_slug,
    get_github_client,
    get_redis_client,
    get_deployment_queue,
    flash,
    get_translation as _,
    TemplateResponse,
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
)
from config import get_settings, Settings
from db import get_db
from services.github import GitHub
from utils.github import get_installation_instance
from utils.projects import get_latest_projects, get_latest_deployments
from utils.teams import get_latest_teams
from utils.pagination import paginate
from utils.environments import group_branches_by_environment
from utils.colors import COLORS

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/{team_slug}/repo-select", methods=["GET", "POST"], name="project_repo_select")
async def repo_select(
    request: Request,
    account: str | None = None,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    github_client: GitHub = Depends(get_github_client),
):
    team, membership = team_and_membership
    
    accounts = []
    selected_account = None
    try:
        if not current_user.github_token:
            raise ValueError("GitHub token missing.")

        installations = await github_client.get_user_installations(
            current_user.github_token
        )
        accounts = [installation["account"]["login"] for installation in installations]
        selected_account = account or (accounts[0] if accounts else None)
    except Exception:
        flash(request, _("Error fetching installations from GitHub."), "error")

    return TemplateResponse(
        request=request,
        name="projects/partials/_repo-select.html",
        context={
            "current_user": current_user,
            "team": team,
            "accounts": accounts,
            "selected_account": selected_account,
        },
    )


@router.get("/{team_slug}/new-project", name="new_project")
async def new_project(
    request: Request,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
):
    team, membership = team_and_membership

    return TemplateResponse(
        request=request,
        name="projects/pages/new.html",
        context={
            "current_user": current_user,
            "team": team,
        },
    )


@router.api_route("/{team_slug}/new-project/details", methods=["GET", "POST"], name="new_project_details")
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
    github_client: GitHub = Depends(get_github_client),
):
    team, membership = team_and_membership
    
    if not all([repo_id, repo_owner, repo_name, repo_default_branch]):
        flash(request, _("Missing repository details."), "error")
        return RedirectResponse(request.url_for("project_new", team_slug=team.slug), status_code=303)
    
    form: Any = await NewProjectForm.from_formdata(
        request, 
        db=db, 
        team=team
    )

    if request.method == "GET":
        form.repo_id.data = int(repo_id)
        form.name.data = repo_name
        form.production_branch.data = repo_default_branch

    if request.method == "POST" and await form.validate_on_submit():
        try:
            if not current_user.github_token:
                raise ValueError("GitHub token missing.")

            if not form.repo_id.data:
                raise ValueError("Repository ID missing.")

            repo = await github_client.get_repository(
                current_user.github_token, int(form.repo_id.data)
            )
        except Exception:
            flash(request, "You do not have access to this repository.", "error")
            return RedirectResponse(request.url_for("project_new", team_slug=team.slug), status_code=303)

        installation = await github_client.get_repository_installation(
            repo["full_name"]
        )
        github_installation = await get_installation_instance(
            installation["id"], db, github_client
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
        )

        db.add(project)
        await db.commit()
        flash(request, _("Project added."), "success")
        return RedirectResponse(
            request.url_for("project_index", team_slug=team.slug, project_name=project.name), status_code=303
        )

    return TemplateResponse(
        request=request,
        name="projects/pages/new-details.html",
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

    if request.headers.get('HX-Request') and fragment == 'deployments':
        return TemplateResponse(
            request=request,
            name="projects/partials/_index_deployments.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployments": deployments,
                "env_aliases": env_aliases,
            },
        )

    latest_teams = await get_latest_teams(db=db, current_team=team, limit=5)
    latest_projects = await get_latest_projects(db=db, current_project=project, limit=5)

    return TemplateResponse(
        request=request,
        name="projects/pages/index.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "deployments": deployments,
            "apps_base_domain": settings.base_domain,
            "env_aliases": env_aliases,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
        },
    )


@router.get("/{team_slug}/projects/{project_name}/deployments", name="project_deployments")
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

    # Filter by environment
    if environment:
        environment_object = project.get_environment_by_slug(environment)
        if environment_object:
            query = query.where(Deployment.environment_id == environment_object.get("id"))

    # Filter by status (conclusion)
    if status:
        if status == "in_progress":
            query = query.where(Deployment.conclusion == None)
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
            name="projects/partials/_deployments.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployments": pagination.get("items"),
                "pagination": pagination,
                "env_aliases": env_aliases,
            },
        )

    latest_teams = await get_latest_teams(db=db, current_team=team, limit=5)
    latest_projects = await get_latest_projects(db=db, current_project=project, limit=5)

    return TemplateResponse(
        request=request,
        name="projects/pages/deployments.html",
        context={
            "current_user": current_user,
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


@router.api_route("/{team_slug}/projects/{project_name}/deploy", methods=["GET", "POST"], name="project_deploy")
async def project_deploy(
    request: Request,
    environment_id: str = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    github_client: GitHub = Depends(get_github_client),
    redis_client: Redis = Depends(get_redis_client),
    deployment_queue: ArqRedis = Depends(get_deployment_queue),
):
    team, membership = team_and_membership
    
    form: Any = await ProjectDeployForm.from_formdata(request, project=project)

    environment_choices = []
    for env in project.active_environments:
        environment_choices.append((env["id"], env["name"]))
    form.environment_id.choices = environment_choices

    if not form.environment_id.data:
        form.environment_id.data = environment_id
    environment = project.get_environment_by_id(form.environment_id.data)

    if not environment:
        error_message = _("Error deploying %(project)s: Environment not found") % {
            "project": project.name
        }
        logger.error(error_message)
        flash(request, error_message, "error")
        return RedirectResponse(
            request.url_for("project_deploy", team_slug=team.slug, project_name=project.name),
            status_code=303,
        )

    if request.method == "POST" and await form.validate_on_submit():
        try:
            if not current_user.github_token:
                raise ValueError("GitHub token missing.")

            if not form.commit.data:
                raise ValueError("Commit missing.")

            branch, commit_sha = form.commit.data.split(":")
            commit = await github_client.get_repository_commit(
                user_access_token=current_user.github_token,
                repo_id=project.repo_id,
                commit_sha=commit_sha,
                branch=branch,
            )

            deployment = Deployment(
                project=project,
                environment_id=environment.get("id", ""),
                trigger="user",
                branch=branch,
                commit_sha=commit["sha"],
                commit_meta={
                    "author": commit["author"]["login"],
                    "message": commit["commit"]["message"],
                    "date": datetime.fromisoformat(
                        commit["commit"]["author"]["date"].replace("Z", "+00:00")
                    ).isoformat(),
                },
            )
            db.add(deployment)
            await db.commit()

            await redis_client.xadd(
                f"stream:project:{project.id}:updates",
                fields={
                    "event_type": "deployment_created",
                    "project_id": project.id,
                    "deployment_id": deployment.id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            await deployment_queue.enqueue_job("deploy", deployment.id)
            logger.info(
                f"Deployment {deployment.id} created and queued for "
                f"project {project.name} ({project.id}) to environment {environment.get("name")} ({environment.get("id")})"
            )

            if request.headers.get("HX-Request"):
                return Response(
                    status_code=200,
                    headers={
                        "HX-Redirect": str(
                            request.url_for(
                                "project_deployment",
                                team_slug=team.slug,
                                project_name=project.name,
                                deployment_id=deployment.id,
                            )
                        )
                    },
                )
            else:
                return RedirectResponse(
                    url=request.url_for(
                        "project_deployment",
                        team_slug=team.slug,
                        project_name=project.name,
                        deployment_id=deployment.id,
                    ),
                    status_code=303,
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
        if not current_user.github_token:
            raise ValueError("GitHub token missing.")

        branches = await github_client.get_repository_branches(
            current_user.github_token, project.repo_id
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
        matching_branches = branches_by_environment.get(environment["slug"])

        # Get the latest 5 commits for each matching branch
        if matching_branches:
            for branch in matching_branches:
                try:
                    if not current_user.github_token:
                        raise ValueError("GitHub token missing.")

                    branch_commits = await github_client.get_repository_commits(
                        current_user.github_token, project.repo_id, branch, per_page=5
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
        name="projects/partials/_dialog-deploy-commits.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "form": form,
            "commits": commits,
        },
    )


@router.api_route("/{team_slug}/projects/{project_name}/settings", methods=["GET", "POST"], name="project_settings")
async def project_settings(
    request: Request,
    fragment: str = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    team, membership = team_and_membership

    # Delete
    delete_project_form: Any = await ProjectDeleteForm.from_formdata(
        request, project=project
    )
    if request.method == "POST" and fragment == "danger":
        if await delete_project_form.validate_on_submit():
            try:
                project.status = "deleted"
                await db.commit()

                # Project is marked as deleted, actual cleanup is delegated to a job
                # TODO: job_timeout='1h'
                deployment_queue = await get_deployment_queue()
                await deployment_queue.enqueue_job("cleanup", project.id)

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

        return RedirectResponse(
            url=str(request.url_for("project_settings", team_slug=team.slug, project_name=project.name))
            + "#danger",
            status_code=303,
        )

    # General
    general_form: Any = await ProjectGeneralForm.from_formdata(
        request, 
        data={"name": project.name, "repo_id": project.repo_id},
        db=db,
        team=team,
        project=project
    )

    if fragment == "general":
        if request.method == "POST" and await general_form.validate_on_submit():
            # Name
            old_name = project.name
            project.name = general_form.name.data or ""

            # Repo
            if general_form.repo_id.data != project.repo_id:
                try:
                    github_client = get_github_client()
                    repo = await github_client.get_repository(current_user.github_token or "", general_form.repo_id.data)
                except Exception as e:
                    flash(request, _("You do not have access to this repository."), "error")
                project.repo_id = general_form.repo_id.data
                project.repo_full_name = repo.get('full_name') or ""

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
                new_url = request.url_for("project_settings", team_slug=team.slug, project_name=project.name)

                if request.headers.get("HX-Request"):
                    return Response(
                        status_code=200, headers={"HX-Redirect": str(new_url)}
                    )
                else:
                    return RedirectResponse(new_url, status_code=303)

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="projects/partials/_settings-general.html",
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
                name="projects/partials/settings/_env_vars.html",
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
                flash(request, str(e), "error")

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
                flash(request, str(e), "error")

    if fragment in ("environment", "delete_environment") and request.headers.get("HX-Request"):
        return TemplateResponse(
            request=request,
            name="projects/partials/settings/_environments.html",
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
                name="projects/partials/settings/_build_and_deploy.html",
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
        name="projects/pages/settings.html",
        context={
            "current_user": current_user,
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


@router.get("/{team_slug}/projects/{project_name}/deployments/{deployment_id}", name="project_deployment")
async def project_deployment(
    request: Request,
    deployment_id: str,
    fragment: str = Query(None),
    project: Project = Depends(get_project_by_name),
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
    deployment: Deployment = Depends(get_deployment_by_id),
):
    team, membership = team_and_membership
    
    env_aliases = await project.get_environment_aliases(db=db)

    if request.headers.get("HX-Request") and fragment == "header":
        return TemplateResponse(
            request=request,
            name="deployments/partials/_header.html",
            context={
                "current_user": current_user,
                "team": team,
                "project": project,
                "deployment": deployment,
                "env_aliases": env_aliases,
            },
        )

    latest_teams = await get_latest_teams(db=db, current_team=team, limit=5)
    latest_projects = await get_latest_projects(db=db, current_project=project, limit=5)
    latest_deployments = await get_latest_deployments(
        db=db, project_id=project.id, current_deployment=deployment, limit=5
    )

    return TemplateResponse(
        request=request,
        name="deployments/pages/index.html",
        context={
            "current_user": current_user,
            "team": team,
            "project": project,
            "deployment": deployment,
            "env_aliases": env_aliases,
            "latest_projects": latest_projects,
            "latest_teams": latest_teams,
            "latest_deployments": latest_deployments,
        },
    )
