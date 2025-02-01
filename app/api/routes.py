from flask import request, current_app, render_template, session, redirect
from flask_login import current_user, login_required
import hmac
import hashlib
from app.api import bp
from app import db
from sqlalchemy import delete, update
from app.models import GithubInstallation, Project
from datetime import datetime
from secrets import token_urlsafe


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
        expected_signature = f"sha256={hash_obj.hexdigest()}"

        if not hmac.compare_digest(signature, expected_signature):
            return '', 401

        event = request.headers.get('X-GitHub-Event')
        data = request.get_json()
        
        current_app.logger.info(f"Received GitHub webhook event: {event}")
        log_message = ""

        match event:
            case "installation":
                if data['action'] == "deleted" or data['action'] == "suspended":
                    # App uninstalled or suspended
                    deleted_tokens = db.session.execute(
                        delete(GithubInstallation).where(GithubInstallation.installation_id == data['installation']['id'])
                    )
                    if deleted_tokens:
                        log_message = f"Deleted installation {data['installation']['id']}"
                elif data['action'] == "created" or data['action'] == "unsuspended":
                    # App installed or unsuspended
                    installation_id = data['installation']['id']
                    token_data = current_app.github.get_installation_access_token(installation_id)
                    
                    installation = GithubInstallation(
                        installation_id=installation_id,
                        token=token_data['token'],
                        token_expires_at=datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
                    )
                    db.session.merge(installation)
                    log_message = f"Added/updated installation {installation_id}"
            
            case "installation_target":
                if data['action'] == "renamed":
                    # Installation account is renamed
                    installation_id = data['installation']['id']
                    token_data = current_app.github.get_installation_access_token(installation_id)
                    
                    installation = GithubInstallation(
                        installation_id=installation_id,
                        token=token_data['token'],
                        token_expires_at=datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
                    )
                    db.session.merge(installation)
                    log_message = f"Updated installation {installation_id}"

            # case "installation_repositories":
            #     if data['action'] == "removed":
            #         # Repositories are removed from installation
            #         removed_repos = data['repositories_removed']
            #         repo_ids = [repo['id'] for repo in removed_repos]
            #         db.session.execute(
            #             update(Project)
            #             .where(Project.repo_id.in_(repo_ids))
            #             .values(status='repo_removed')
            #         )
            #         log_message = f"Marked projects as removed for repos: {', '.join(repo_ids)}"

            #     elif data['action'] == "added":
            #         # Repositories are added to installation
            #         added_repos = data['repositories_added']
            #         repo_ids = [repo['id'] for repo in added_repos]
            #         db.session.execute(
            #             update(Project)
            #             .where(Project.repo_id.in_(repo_ids))
            #             .values(status='active')
            #         )
            #         log_message = f"Marked projects as added for repos: {', '.join(repo_ids)}"

            case "repository":
                # if data['action'] == "deleted" or data['action'] == "transferred":
                #     # Repository is deleted or transferred
                #     db.session.execute(
                #         update(Project)
                #         .where(Project.repo_id == data['repository']['id'])
                #         .values(status='repo_removed')
                #     )
                #     log_message = f"Marked project as removed for repo: {data['repository']['id']}"

                if data['action'] == "renamed":
                    # Repository is renamed
                    result = db.session.execute(
                        update(Project)
                        .where(Project.repo_id == data['repository']['id'])
                        .values(repo_full_name=data['repository']['full_name'])
                    )
                    log_message = f"Changed name of repo {data['repository']['id']} to {data['repository']['full_name']} for {result.rowcount} projects."

        db.session.commit()
        current_app.logger.info(log_message)
        return '', 200

    except Exception as e:
        current_app.logger.error(f"Error processing GitHub webhook: {str(e)}")
        db.session.rollback()
        return '', 500