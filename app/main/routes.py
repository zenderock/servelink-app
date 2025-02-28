from flask import render_template, redirect, url_for, flash, current_app, request
from flask_babel import _
from flask_login import login_required, current_user
from app import db
from app.main import bp
from app.models import Project, Deployment
from sqlalchemy import select
from app.main.forms import ProjectForm, DeploymentForm
from app.tasks import deploy
from app.helpers.github import get_installation_instance
from app.main.decorators import load_project, load_deployment


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    projects = db.session.scalars(
        select(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Project.updated_at.desc())
    ).all()
    
    deployments = db.session.scalars(
        select(Deployment)
        .join(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Deployment.created_at.desc())
    ).all()
    
    return render_template('index.html', projects=projects, deployments=deployments)


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
        'projects/create-repo.html',
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

    return render_template('projects/create-details.html', repo=repo,  form=form)


@bp.route('/projects/<string:project_name>', methods=['GET', 'POST'])
@login_required
@load_project
def project(project):
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
            return redirect(url_for('main.project', project_name=project.name))
        
        commit = commits[0]

        # We create a new deployment and associate it with the project
        deployment = Deployment(
            project=project,
            trigger='user',
            commit={
                'branch': commit['branch'],
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
        'projects/index.html',
        project=project,
        deployments=deployments,
        pagination=pagination,
        form=form
    )


@bp.route('/projects/<string:project_name>/settings')
@login_required
@load_project
def project_settings(project):
    form = ProjectForm()
    # if form.validate_on_submit():
    #     project.name = form.name.data
    #     project.config = form.config.data
    #     project.env_vars = form.env_vars.data
    #     db.session.commit()
    #     flash(_('Project updated.'))
    #     return redirect(url_for('main.project', project_name=name))
    
    return render_template('projects/settings.html', project=project, form=form)

@bp.route('/projects/<string:project_name>/deployments')
@login_required
@load_project
def deployments(project):
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
            return redirect(url_for('main.project', project_name=project.name))
        
        commit = commits[0]

        # We create a new deployment and associate it with the project
        deployment = Deployment(
            project=project,
            trigger='user',
            commit={
                'branch': commit['branch'],
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
    per_page = 10

    pagination = db.paginate(
        project.deployments.select().order_by(Deployment.created_at.desc()),
        page=page,
        per_page=per_page,
        error_out=False
    )
    deployments = pagination.items

    return render_template(
        'projects/deployments.html',
        project=project,
        deployments=deployments,
        pagination=pagination,
        form=form
    )

@bp.route('/projects/<string:project_name>/deployments/<string:deployment_id>/teaser')
@login_required
@load_project
@load_deployment
def deployment_teaser(project, deployment):
    return render_template('deployments/partials/_teaser.html', deployment=deployment, project=deployment.project)


@bp.route('/projects/<string:project_name>/deployments/<string:deployment_id>')
@login_required
@load_project
@load_deployment
def deployment(project, deployment):
    if request.headers.get('HX-Request'):
        content = render_template('deployments/partials/_logs.html', logs=deployment.parsed_logs)
        code = 200

        if deployment.conclusion:
            code = 286
            content += render_template('deployments/partials/_info.html', deployment=deployment, oob=True)

        return content, code

    return render_template(
        'deployments/index.html', 
        project=deployment.project, 
        deployment=deployment,
        logs=deployment.parsed_logs
    )


@bp.app_context_processor
def inject_latest_projects():
    def get_latest_projects(current_project=None):
        query = Project.query
        if current_project:
            query = query.filter(Project.id != current_project.id)
        return query.order_by(Project.updated_at.desc()).limit(5).all()

    return dict(get_latest_projects=get_latest_projects)


@bp.app_context_processor
def inject_latest_deployments():
    def get_latest_deployments(current_deployment=None):
        query = Deployment.query
        if current_deployment:
            query = query.filter(Deployment.id != current_deployment.id)
        return query.order_by(Deployment.created_at.desc()).limit(5).all()

    return dict(get_latest_deployments=get_latest_deployments)