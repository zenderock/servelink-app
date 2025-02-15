from flask import render_template, redirect, url_for, flash, current_app, request, Response
from flask_babel import _
from flask_login import login_required, current_user
from app import db
from app.main import bp
from app.models import Project, Deployment, GithubInstallation
from sqlalchemy import select
from app.main.forms import ProjectForm, DeploymentForm
from app.tasks.deploy import deploy
from datetime import datetime
from app.helpers.github import get_installation_instance


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    projects = db.session.scalars(
        select(Project).where(Project.user_id == current_user.id)
    ).all()
    return render_template('index.html', projects=projects)


@bp.route('/select-repo')
@login_required
def select_repo():
    installations = current_app.github.get_user_installations(current_user.github_token)
    accounts = [installation['account']['login'] for installation in installations]
    selected_account = request.args.get('account') or (accounts[0] if accounts else None)
    
    query = request.args.get('query', '')
    # TODO: add error handling?
    repos = current_app.github.search_user_repositories(
        current_user.github_token,
        selected_account,
        query
    )

    return render_template(
        'project/new/repo.html',
        accounts=accounts,
        selected_account=selected_account,
        repos=repos,
        query=query
    )


@bp.route('/add-project', methods=['GET', 'POST'])
@login_required
def add_project():
    repo_id = request.args.get('repo_id')
    if not repo_id:
        flash(_('You must select a repository first.'))
        return redirect(url_for('main.select_repo'))
    
    # Make sure the repo suggested is accessible to the user
    try:
        repo = current_app.github.get_repository(current_user.github_token, repo_id)
    except Exception as e:
        flash("You do not have access to this repository.")
        return redirect(url_for('main.select_repo'))
    
    defaults = {
        'repo_id': repo.get('id'),
        'name': repo.get('name')
    }
    form = ProjectForm(request.form or None, **defaults)
    branches = current_app.github.get_repository_branches(current_user.github_token, repo_id)
    form.repo_branch.choices = [(branch['name'], branch['name']) for branch in branches]
    if form.errors:
        print(form.errors)
    if form.validate_on_submit():
        installation = current_app.github.get_repo_installation(repo.get('full_name'))
        # We get the installation instance as this force create/update the token
        github_installation = get_installation_instance(installation.get('id'))
        env_vars = [
            {'key': entry.key.data, 'value': entry.value.data}
            for entry in form.env_vars
        ]
        project = Project(
            name=form.name.data,
            config={
                'runtime': 'cpython',
                'runtime_version': '3.13',
            },
            env_vars=env_vars,
            user=current_user,
            github_installation=github_installation,
            repo_id=form.repo_id.data,
            repo_full_name=repo.get('full_name'),
            repo_branch=form.repo_branch.data
        )
        db.session.add(project)
        db.session.commit()
        flash(_('Project added.'))
        return redirect(url_for('main.index'))

    return render_template('project/new/details.html', repo=repo,  form=form)


# TODO: add decorator for project ownership
@bp.route('/projects/<string:name>', methods=['GET', 'POST'])
@login_required
def project(name):
    project = db.session.scalar(
        select(Project).where(Project.name == name).limit(1)
    )
    if project is None:
        flash(_('Project not found.'), 'error')
        return redirect(url_for('main.index'))
    
    form = DeploymentForm()
    if form.validate_on_submit():
        # We retrieve the latest commit from the repo
        commits = current_app.github.get_repository_commits(
            current_user.github_token,
            project.repo_id,
            project.repo_branch,
            1
        )
        # Error our if no commit (at least one)
        if len(commits) == 0:
            flash(_('No commits found for branch {project.repo_branch}.'), 'error')
            return redirect(url_for('main.project', name=project.name))
        
        commit = commits[0]

        # We create a new deployment and associate it with the project
        deployment = Deployment(
            project=project,
            trigger='user',
            commit={
                'sha': commit['sha'],
                'author': commit['author']['login'],
                'message': commit['commit']['message'],
                'date': commit['commit']['author']['date']
            },
        )
        db.session.add(deployment)
        db.session.commit()
        
        current_app.deployment_queue.enqueue(deploy, deployment.id)

        return redirect(url_for('main.deployment', project_name=project.name, deployment_id=deployment.id))
    
    page = request.args.get('page', 1, type=int)
    per_page = 25

    pagination = db.paginate(
        project.deployments.select().order_by(Deployment.created_at.desc()),
        page=page,
        per_page=per_page,
        error_out=False
    )
    deployments = pagination.items

    return render_template(
        'project/index.html',
        project=project,
        deployments=deployments,
        pagination=pagination,
        form=form
    )


@bp.route('/project/<string:name>/settings')
@login_required
def project_settings(name):
    # project = db.session.scalar(
    #     select(Project).where(Project.name == name)
    # )
    # if not project:
    #     flash(_('Project not found.'), 'error')
    #     return redirect(url_for('main.project', name=name))
    
    form = ProjectForm()
    # if form.validate_on_submit():
    #     project.name = form.name.data
    #     project.config = form.config.data
    #     project.env_vars = form.env_vars.data
    #     db.session.commit()
    #     flash(_('Project updated.'))
    #     return redirect(url_for('main.project', name=name))
    
    return render_template('project/settings.html', project=project, form=form)


@bp.route('/project/<string:project_name>/deployments/<string:deployment_id>/teaser')
@login_required
def deployment_teaser(project_name, deployment_id):
    deployment = db.session.scalar(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    
    if not deployment:
        return _('Deployment not found.'), 404

    return render_template('deployment/components/_teaser.html', deployment=deployment, project=deployment.project)


# TODO: add decorator for project ownership
@bp.route('/project/<string:project_name>/deployments/<string:deployment_id>')
@login_required
def deployment(project_name, deployment_id):
    deployment = db.session.scalar(
        select(Deployment).where(Deployment.id == deployment_id)
    )

    if not deployment:
        flash(_('Deployment not found.'), 'error')
        return redirect(url_for('main.project', name=deployment.project.name))
    
    # If it's an HTMX request, we just return the details
    if request.headers.get('HX-Request'):
        return render_template('deployment/components/_details.html', deployment=deployment)
    
    # Get historical logs
    raw_logs = []
    logs = []
    latest_timestamp = None

    if deployment.build_logs:
        raw_logs = deployment.build_logs.splitlines()
    elif (deployment.container_id):
        raw_logs = current_app.docker_client.containers.get(deployment.container_id).logs(
            stream=False,
            timestamps=True
        ).decode('utf-8').splitlines()

    for line in raw_logs:
        timestamp, message = line.split(' ', 1)
        try:
            latest_timestamp = datetime.fromisoformat(timestamp.rstrip('Z')).timestamp()
        except ValueError:
            latest_timestamp = None
        logs.append({
            'timestamp': latest_timestamp,
            'message': message
        })
    
    return render_template(
        'deployment/index.html', 
        project=deployment.project, 
        deployment=deployment, 
        logs=logs,
        latest_timestamp=latest_timestamp
    )


@bp.route('/project/<string:project_name>/deployments/<string:deployment_id>/logs/stream')
@login_required
def deployment_logs_stream(project_name, deployment_id):
    deployment = db.session.scalar(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    if deployment is None:
        return Response(
            'event: warning\ndata: Deployment not found\n\n',
            mimetype='text/event-stream'
        )

    if not deployment.container_id:
        return Response(
            'event: warning\ndata: No container ID found for deployment\n\n',
            mimetype='text/event-stream'
        )

    try:
        since = float(request.args.get('since', None))
    except (TypeError, ValueError):
        since = None

    app = current_app._get_current_object()
    container = None
    log_stream = None

    def stream_logs():
        nonlocal container, log_stream, deployment

        def format_log_message(line: bytes) -> str:
            # Decode and split the log line into a timestamp and a message.
            timestamp, message = line.decode('utf-8').split(' ', 1)
            formatted_log = render_template(
                'deployment/components/_log.html',
                log={
                    'timestamp': datetime.fromisoformat(timestamp.rstrip('Z')).timestamp(),
                    'message': message,
                }
            ).replace('\n', ' ').strip()
            return f"data: {formatted_log}\n\n"
        
        with app.app_context():
            deployment = db.session.scalar(
                select(Deployment).where(Deployment.id == deployment_id)
            )
            try:
                container = app.docker_client.containers.get(deployment.container_id)
                log_stream = container.logs(
                    stream=True,
                    follow=True,
                    stdout=True,
                    stderr=True,
                    timestamps=True,
                    since=since
                )
                
                for line in log_stream:
                    yield format_log_message(line)
                    db.session.refresh(deployment)
                    if deployment.conclusion:
                        yield f"event: close\ndata: Deployment {deployment.conclusion}\n\n"
                        break
                
                # If the log stream gets interrupted (e.g. the container was stopped because of a deployment error), we close it
                app.logger.error('Deployment interrupted')
                db.session.refresh(deployment)
                yield f"event: close\ndata: Deployment {deployment.conclusion}\n\n"
                return
            
            except Exception as e:
                app.logger.info('Stream failure')
                db.session.refresh(deployment)
                yield f"event: close\ndata: Deployment {deployment.conclusion}\n\n"
                return
            
            finally:
                app.logger.error('Cleanup')
                # We clean everything up
                if log_stream:
                    log_stream.close()
                if container:
                    container.client.close()

    return Response(
        stream_logs(),
        mimetype='text/event-stream'
    )


@bp.route('/kitchen-sink')
def kitchen_sink():
    return render_template('kitchen-sink.html')