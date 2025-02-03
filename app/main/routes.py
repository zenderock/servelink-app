from flask import render_template, redirect, url_for, flash, current_app, request
from flask_babel import _
from flask_login import login_required, current_user
from app import db
from app.main import bp
from app.models import Project, Deployment
from sqlalchemy import select
from app.main.forms import ProjectForm, DeploymentForm
from app.tasks.deploy import deploy


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
    
    form = ProjectForm()
    repo = current_app.github.get_repository(current_user.github_token, repo_id)
    branches = current_app.github.get_repository_branches(current_user.github_token, repo_id)
    form.repo_branch.choices = [(branch['name'], branch['name']) for branch in branches]
    
    if form.validate_on_submit():
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
            repo_id=form.repo_id.data,
            repo_full_name=repo.get('full_name'),
            repo_branch=form.repo_branch.data
        )
        db.session.add(project)
        db.session.commit()
        flash(_('Project added.'))
        return redirect(url_for('main.index'))
    # else:
    #     print('Form validation failed:', form.errors)
    #     flash(_('Please check the form for errors.'), 'error')

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
        # We create a new deployment and associate it with the project
        deployment = Deployment(
            project=project,
            trigger='user',
            commit_sha='312673e537c4cdb2697f5057bfcb0ec26f3e9dc4',
        )
        db.session.add(deployment)
        db.session.commit()
        
        current_app.deployment_queue.enqueue(deploy, deployment.id)

        return redirect(url_for('main.project', name=project.name))
    
    deployments = db.session.scalars(
        project.deployments.select()
    ).all()

    return render_template('project/index.html', project=project, deployments=deployments, form=form)


# TODO: add decorator for project ownership
@bp.route('/project/<string:name>/deployments/<string:deployment_id>')
@login_required
def deployment(name, deployment_id):
    deployment = db.session.scalar(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    if deployment is None:
        flash(_('Deployment not found.'), 'error')
        return redirect(url_for('main.project', name=deployment.project.name))
    # if deployment.conclusion != 'succeeded':
    #     flash(_('Deployment failed, canceled or skipped.'), 'error')
    #     return redirect(url_for('main.project', name=deployment.project.name))
    # We retrieve the logs from the deployment 
    logs = current_app.docker_client.containers.get(deployment.container_id).logs()
    print(logs)
    
    return render_template('deployment/index.html', deployment=deployment)


@bp.route('/kitchen-sink')
def kitchen_sink():
    return render_template('kitchen-sink.html')