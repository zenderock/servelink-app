from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from secrets import token_urlsafe
# from sqlalchemy import update, select
# from datetime import datetime

# from app.models import GithubInstallation, Project, Deployment
# from app.tasks.deploy import deploy
# from app.helpers.environments import get_environment_for_branch
from config import get_settings
from dependencies import get_current_user, get_github_service, TemplateResponse
from models import User
from services.github import GitHub

router = APIRouter(prefix="/github")


@router.get("/repos", name="github_repos")
async def github_repos(
    request: Request,
    current_user: User = Depends(get_current_user),
    github: GitHub = Depends(get_github_service),
    account: str | None = None,
    query: str | None = None
):
    
    repos = github.search_user_repositories(
        current_user.github_token,
        account or "",
        query or ""
    )
    return TemplateResponse(
        "projects/partials/_repo-select-list.html",
        {
            "request": request,
            "repos": repos
        }
    )





@router.get("/install", name="github_app_install")
async def github_app_install(request: Request):
    state = token_urlsafe(32)
    request.session['github_state'] = state
    settings = get_settings()

    github_install_url = (
        f"https://github.com/apps/{settings.github_app_name}/installations/select_target"
        f"?state={state}"
    )
    return RedirectResponse(github_install_url)


# @bp.route('/github/webhook', methods=['POST'])
# def github_webhook():
#     try:
#         # Verify webhook signature
#         signature = request.headers.get('X-Hub-Signature-256')
#         payload = request.get_data()
#         secret = current_app.config['GITHUB_APP_WEBHOOK_SECRET'].encode()
#         hash_obj = hmac.new(secret, msg=payload, digestmod=hashlib.sha256)
#         expected_signature = f'sha256={hash_obj.hexdigest()}'

#         if not hmac.compare_digest(signature, expected_signature):
#             current_app.logger.info(f'INVALID GitHub webhook event: {event}')
#             return '', 401

#         event = request.headers.get('X-GitHub-Event')
#         data = request.get_json()
        
#         current_app.logger.info(f'Received GitHub webhook event: {event}')

#         match event:
#             case 'installation':
#                 if data['action'] == 'deleted' or data['action'] == 'suspended' or data['action'] == 'unsuspended':
#                     # App uninstalled or suspended
#                     status = 'active' if data['action'] == 'unsuspended' else data['action']
#                     db.session.execute(
#                         update(GithubInstallation)
#                         .where(GithubInstallation.installation_id == data['installation']['id'])
#                         .values(status=status)
#                     )
#                     current_app.logger.info(f"Installation {data['installation']['id']} for {data['installation']['account']['login']} is {data['action']}")
                        
#                 elif data['action'] == "created":
#                     # App installed
#                     installation_id = data['installation']['id']
#                     token_data = current_app.github.get_installation_access_token(installation_id)
#                     installation = GithubInstallation(
#                         installation_id=installation_id,
#                         token=token_data['token'],
#                         token_expires_at=datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
#                     )
#                     db.session.merge(installation)
#                     current_app.logger.info(f'Installation {installation_id} for {data["installation"]["account"]["login"]} created')
            
#             case 'installation_target':
#                 if data['action'] == 'renamed':
#                     # Installation account is renamed (not used)
#                     pass

#             case 'installation_repositories':
#                 if data['action'] == 'removed':
#                     # Repositories removed from installation
#                     removed_repos = data['repositories_removed']
#                     repo_ids = [repo['id'] for repo in removed_repos]
#                     db.session.execute(
#                         update(Project)
#                         .where(Project.repo_id.in_(repo_ids))
#                         .values(status='removed')
#                     )
#                     current_app.logger.info(f"Repos removed from installation {data['installation']['id']} for {data['installation']['account']['login']}: {', '.join(repo_ids)}")

#                 elif data['action'] == 'added':
#                     # Repositories are added to installation
#                     added_repos = data['repositories_added']
#                     repo_ids = [repo['id'] for repo in added_repos]
#                     db.session.execute(
#                         update(Project)
#                         .where(Project.repo_id.in_(repo_ids))
#                         .values(status='active')
#                     )
#                     current_app.logger.info(f"Repos added to installation: {', '.join(repo_ids)}")

#             case 'repository':
#                 if data['action'] == 'deleted' or data['action'] == 'transferred':
#                     # Repository is deleted or transferred
#                     db.session.execute(
#                         update(Project)
#                         .where(Project.repo_id == data['repository']['id'])
#                         .values(repo_status=data['action'])
#                     )
#                     current_app.logger.info(f"Repo {data['repository']['id']} is {data['action']}")

#                 if data['action'] == "renamed":
#                     # Repository is renamed
#                     db.session.execute(
#                         update(Project)
#                         .where(Project.repo_id == data['repository']['id'])
#                         .values(repo_full_name=data['repository']['full_name'])
#                     )
#                     current_app.logger.info(f"Repo {data['repository']['id']} renamed to {data['repository']['full_name']}")
            
#             case 'push':
#                 # Code pushed to a repository
#                 projects = db.session.scalars(
#                     select(Project)
#                     .where(
#                         Project.repo_id == data['repository']['id'],
#                         Project.status == 'active'
#                     )
#                 ).all()
                
#                 if not projects:
#                     current_app.logger.info(f"No projects found for repo {data['repository']['id']}")
#                     return '', 200
                
#                 branch = data['ref'].replace('refs/heads/', '')  # Convert refs/heads/main to main
                
#                 for project in projects:
#                     # Check if branch matches any environment
#                     matched_env = get_environment_for_branch(branch, project.active_environments)
#                     if not matched_env:
#                         current_app.logger.info(
#                             f"Skipping deployment for project {project.name}: "
#                             f"branch '{branch}' doesn't match any environment"
#                         )
#                         continue

#                     deployment = Deployment(
#                         project=project,
#                         environment_id=matched_env['id'],
#                         trigger='webhook',
#                         branch=branch,
#                         commit_sha=data['after'],
#                         commit_meta={
#                             'author': data['pusher']['name'],
#                             'message': data['head_commit']['message'],
#                             'date': datetime.fromisoformat(data['head_commit']['timestamp'].replace('Z', '+00:00')).isoformat()
#                         },
#                     )
#                     db.session.add(deployment)
#                     db.session.commit()

#                     current_app.deployment_queue.enqueue(deploy, deployment.id)
#                     current_app.logger.info(
#                         f'Deployment {deployment.id} created and queued for '
#                         f'project {project.name} ({project.id}) to environment {matched_env.get('slug')}'
#                     )

#             case 'pull_request':
#                 # TODO: Add logic for PRs
#                 pass


#         return '', 200

#     except Exception as e:
#         import traceback
#         current_app.logger.error(f'Error processing GitHub webhook: {str(e)}', exc_info=True)
#         db.session.rollback()
#         return '', 500