from flask import request, current_app, render_template, session, redirect
from flask_login import current_user, login_required
import hmac
import hashlib
from app.api import bp
from app import db
from sqlalchemy import update, select
from app.models import GithubInstallation, Project, Deployment
from datetime import datetime
from secrets import token_urlsafe
from app.tasks.deploy import deploy


@bp.route('/github/repos', methods=['GET'])
@login_required
def github_repos():
    account = request.args.get('account')
    query = request.args.get('query')
    repos = current_app.github.search_user_repositories(
        current_user.github_token,
        account,
        query
    )
    return render_template('project/components/repo/_list.html', repos=repos)


@bp.route('/github/install')
@login_required
def github_app_install():
    state = token_urlsafe(32)
    session['github_state'] = state

    github_install_url = (
        f"https://github.com/apps/{current_app.config['GITHUB_APP_NAME']}/installations/new"
        f"?state={state}"
    )
    return redirect(github_install_url)


@bp.route('/github/webhook', methods=['POST'])
def github_webhook():
    try:
        # Verify webhook signature
        signature = request.headers.get('X-Hub-Signature-256')
        payload = request.get_data()
        secret = current_app.config['GITHUB_APP_WEBHOOK_SECRET'].encode()
        hash_obj = hmac.new(secret, msg=payload, digestmod=hashlib.sha256)
        expected_signature = f'sha256={hash_obj.hexdigest()}'

        if not hmac.compare_digest(signature, expected_signature):
            current_app.logger.info(f'INVALID GitHub webhook event: {event}')
            return '', 401

        event = request.headers.get('X-GitHub-Event')
        data = request.get_json()
        
        current_app.logger.info(f'Received GitHub webhook event: {event}')

        match event:
            case 'installation':
                if data['action'] == 'deleted' or data['action'] == 'suspended' or data['action'] == 'unsuspended':
                    # App uninstalled or suspended
                    status = 'active' if data['action'] == 'unsuspended' else data['action']
                    db.session.execute(
                        update(GithubInstallation)
                        .where(GithubInstallation.installation_id == data['installation']['id'])
                        .values(status=status)
                    )
                    current_app.logger.info(f"Installation {data['installation']['id']} for {data['installation']['account']['login']} is {data['action']}")
                        
                elif data['action'] == "created":
                    # App installed
                    installation_id = data['installation']['id']
                    token_data = current_app.github.get_installation_access_token(installation_id)
                    installation = GithubInstallation(
                        installation_id=installation_id,
                        token=token_data['token'],
                        token_expires_at=datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
                    )
                    db.session.merge(installation)
                    current_app.logger.info(f'Installation {installation_id} for {data["installation"]["account"]["login"]} created')
            
            case 'installation_target':
                if data['action'] == 'renamed':
                    # Installation account is renamed (not used)
                    pass

            case 'installation_repositories':
                if data['action'] == 'removed':
                    # Repositories removed from installation
                    removed_repos = data['repositories_removed']
                    repo_ids = [repo['id'] for repo in removed_repos]
                    db.session.execute(
                        update(Project)
                        .where(Project.repo_id.in_(repo_ids))
                        .values(status='removed')
                    )
                    current_app.logger.info(f"Repos removed from installation {data['installation']['id']} for {data['installation']['account']['login']}: {', '.join(repo_ids)}")

                elif data['action'] == 'added':
                    # Repositories are added to installation
                    added_repos = data['repositories_added']
                    repo_ids = [repo['id'] for repo in added_repos]
                    db.session.execute(
                        update(Project)
                        .where(Project.repo_id.in_(repo_ids))
                        .values(status='active')
                    )
                    current_app.logger.info(f"Repos added to installation: {', '.join(repo_ids)}")

            case 'repository':
                if data['action'] == 'deleted' or data['action'] == 'transferred':
                    # Repository is deleted or transferred
                    db.session.execute(
                        update(Project)
                        .where(Project.repo_id == data['repository']['id'])
                        .values(repo_status=data['action'])
                    )
                    current_app.logger.info(f"Repo {data['repository']['id']} is {data['action']}")

                if data['action'] == "renamed":
                    # Repository is renamed
                    db.session.execute(
                        update(Project)
                        .where(Project.repo_id == data['repository']['id'])
                        .values(repo_full_name=data['repository']['full_name'])
                    )
                    current_app.logger.info(f"Repo {data['repository']['id']} renamed to {data['repository']['full_name']}")
            
            case 'push':
                # Code pushed to a repository
                projects = db.session.execute(
                    select(Project)
                    .where(Project.repo_id == data['repository']['id'])
                ).scalars().all()
                
                if not projects:
                    current_app.logger.info(f"No projects found for repo {data['repository']['id']}")
                    return '', 200
                
                for project in projects:
                    deployment = Deployment(
                        project=project,
                        trigger='webhook',
                        commit={
                            'sha': data['after'],
                            'author': data['pusher']['name'],
                            'message': data['head_commit']['message'],
                            'date': datetime.fromisoformat(data['head_commit']['timestamp'].replace('Z', '+00:00')).isoformat()
                        },
                    )
                    db.session.add(deployment)
                    db.session.commit()

                    current_app.deployment_queue.enqueue(deploy, deployment.id)
                    current_app.logger.info(f'Deployment {deployment.id} created and queued for project {project.name} ({project.id})')

            case 'pull_request':
                # TODO: Add logic for PRs
                pass


        return '', 200

    except Exception as e:
        current_app.logger.error(f'Error processing GitHub webhook: {str(e)}')
        db.session.rollback()
        return '', 500