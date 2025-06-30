from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from secrets import token_urlsafe

from models import Project, Deployment, User
from dependencies import TemplateResponse, get_current_user, get_github_service, flash
from services.github import GitHub
from db import get_db

router = APIRouter()


@router.get("/", name="team_index")
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    projects_result = await db.execute(
        select(Project)
        .where(
            Project.user_id == current_user.id,
            Project.status != 'deleted'
        )
        .order_by(Project.updated_at.desc())
        .limit(6)
    )
    projects = projects_result.scalars().all()
    
    deployments_result = await db.execute(
        select(Deployment)
        .join(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Deployment.created_at.desc())
        .limit(10)
    )
    deployments = deployments_result.scalars().all()
    
    return TemplateResponse(
        "pages/index.html",
        {
            "request": request,
            "current_user": current_user,
            "projects": projects,
            "deployments": deployments
        }
    )

@router.get("/repo-select", name="team_repo_select")
async def repo_select(
    request: Request,
    account: str | None = None,
    current_user: User = Depends(get_current_user),
    github: GitHub = Depends(get_github_service)
):
    accounts = []
    selected_account = None
    try:
        installations = github.get_user_installations(current_user.github_token)
        accounts = [installation['account']['login'] for installation in installations]
        selected_account = account or (accounts[0] if accounts else None)
    except Exception as e:
        flash(request, 'Error fetching installations from GitHub.', 'error')
    
    return TemplateResponse(
        "projects/partials/_repo-select.html",
        {
            "request": request,
            "accounts": accounts,
            "selected_account": selected_account
        }
    )


@router.get("/new-project", name="team_new_project")
async def new_project(request: Request):
    return TemplateResponse(
        "projects/pages/new/repo.html",
        {"request": request}
    )


# @router.get("/new-project/details", name="team_new_project_details")
# async def new_project_details(
#     request: Request,
#     current_user: User = Depends(get_current_user),
#     github: GitHub = Depends(get_github_service),
#     db: AsyncSession = Depends(get_db),
#     repo_id: str = Query(None),
#     repo_owner: str = Query(None),
#     repo_name: str = Query(None),
#     repo_default_branch: str = Query(None)
# ):
#     if not repo_id or not repo_owner or not repo_name or not repo_default_branch:
#         flash(request, 'Missing repository details.', 'error')
#         return RedirectResponse(url_for('team_new_project'))
    
#     defaults = {
#         'repo_id': repo_id,
#         'name': repo_name,
#         'production_branch': repo_default_branch
#     }
#     form = ProjectForm(request.form or None, **defaults)
    
#     if form.validate_on_submit():
#         # Make sure the repo suggested is accessible to the user
#         try:
#             repo = current_app.github.get_repository(current_user.github_token, repo_id)
#         except Exception as e:
#             flash("You do not have access to this repository.")
#             return redirect(url_for('team_new_project'))

#         installation = current_app.github.get_repository_installation(repo.get('full_name'))
#         # Get the installation instance as this force create/update the token
#         github_installation = get_installation_instance(installation.get('id'))
#         env_vars = [
#             {'key': entry.key.data, 'value': entry.value.data}
#             for entry in form.env_vars
#         ]
        
#         project = Project(
#             name=form.name.data,
#             repo_id=form.repo_id.data,
#             repo_full_name=repo.get('full_name'),
#             github_installation=github_installation,
#             config={
#                 'framework': form.framework.data,
#                 'runtime': form.runtime.data,
#                 'root_directory': form.root_directory.data if form.use_custom_root_directory.data else None,
#                 'build_command': form.build_command.data if form.use_custom_build_command.data else None,
#                 'pre_deploy_command': form.pre_deploy_command.data if form.use_custom_pre_deploy_command.data else None,
#                 'start_command': form.start_command.data if form.use_custom_start_command.data else None
#             },
#             env_vars=env_vars,
#             environments=[{
#                 'id': 'prod',
#                 'color': 'blue',
#                 'name': 'Production',
#                 'slug': 'production',
#                 'branch': form.production_branch.data,
#                 'status': 'active'
#             }],
#             user=current_user
#         )
#         db.session.add(project)
#         db.session.commit()
#         flash(_('Project added.'), 'success')
#         return redirect(url_for('team.project', project_name=project.name))

#     return render_template(
#         'projects/pages/new/details.html',
#         form=form,
#         repo_full_name=f"{repo_owner}/{repo_name}",
#         frameworks=current_app.frameworks,
#         environments=[{
#             'color': 'blue',
#             'name': 'Production',
#             'slug': 'production'
#         }]
#     )
