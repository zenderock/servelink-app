from flask import render_template, redirect, url_for, flash, current_app, request
from flask_babel import _
from flask_login import login_required, current_user
from app import db
from app.main import bp
from app.models import Project, Deployment
from sqlalchemy import select
from app.main.forms import ProjectForm, DeploymentForm, ProdEnvironmentForm, CustomEnvironmentForm, EnvVarsForm, BuildAndDeployForm, GeneralForm, DeleteEnvironmentForm
from app.tasks import deploy
from app.helpers.github import get_installation_instance
from app.main.decorators import load_project, load_deployment
from app.helpers.colors import COLORS
from app.helpers.htmx import render_htmx_partial


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    projects = db.session.scalars(
        select(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Project.updated_at.desc())
        .limit(6)
    ).all()
    
    deployments = db.session.scalars(
        select(Deployment)
        .join(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Deployment.created_at.desc())
    ).all()
    
    return render_template('pages/index.html', projects=projects, deployments=deployments)


@bp.route('/repo-select')
@login_required
def repo_select():
    installations = current_app.github.get_user_installations(current_user.github_token)
    accounts = [installation['account']['login'] for installation in installations]
    selected_account = request.args.get('account') or (accounts[0] if accounts else None)
    
    return render_template(
        'projects/partials/_repo-select.html',
        accounts=accounts,
        selected_account=selected_account
    )


@bp.route('/new-project', methods=['GET', 'POST'])
@login_required
def new_project():
    installations = current_app.github.get_user_installations(current_user.github_token)
    accounts = [installation['account']['login'] for installation in installations]
    selected_account = request.args.get('account') or (accounts[0] if accounts else None)
    
    return render_template(
        'projects/pages/new/repo.html',
        accounts=accounts,
        selected_account=selected_account
    )


@bp.route('/new-project-details', methods=['GET', 'POST'])
@login_required
def new_project_details():
    repo_id = request.args.get('repo_id')
    if not repo_id:
        flash(_('You must select a repository first.'))
        return redirect(url_for('main.new_project'))
    
    # Make sure the repo suggested is accessible to the user
    try:
        repo = current_app.github.get_repository(current_user.github_token, repo_id)
    except Exception as e:
        flash("You do not have access to this repository.")
        return redirect(url_for('main.new_project'))
    
    defaults = {
        'repo_id': repo.get('id'),
        'name': repo.get('name'),
        'production_branch': repo.get('default_branch')
    }
    form = ProjectForm(request.form or None, **defaults)
    
    branches = current_app.github.get_repository_branches(current_user.github_token, repo_id)
    form.production_branch.choices = [(branch['name'], branch['name']) for branch in branches]
    
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
            repo_id=form.repo_id.data,
            repo_full_name=repo.get('full_name'),
            github_installation=github_installation,
            config={
                'framework': form.framework.data,
                'runtime': form.runtime.data,
                'root_directory': form.root_directory.data,
                'build_command': form.build_command.data if form.use_custom_build_command.data else None,
                'pre_deploy_command': form.pre_deploy_command.data if form.use_custom_pre_deploy_command.data else None,
                'start_command': form.start_command.data if form.use_custom_start_command.data else None
            },
            env_vars=env_vars,
            environments=[{
                'color': 'blue',
                'name': 'Production',
                'slug': 'production',
                'branch': form.production_branch.data
            }],
            user=current_user
        )
        db.session.add(project)
        db.session.commit()
        flash(_('Project added.'))
        return redirect(url_for('main.index'))

    return render_template('projects/pages/new/details.html', repo=repo,  form=form)


@bp.route('/projects/<string:project_name>', methods=['GET', 'POST'])
@login_required
@load_project
def project(project):
    form = DeploymentForm()
    if form.validate_on_submit():
        # We retrieve the latest commit from the repo
        branch = project.environments[0].get('branch') if project.environments else None
        commits = current_app.github.get_repository_commits(
            current_user.github_token,
            project.repo_id,
            branch,
            1
        )
        # Error our if no commit (at least one)
        if len(commits) == 0:
            flash(_('No commits found for branch {branch}.'), 'error')
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
        'projects/pages/index.html',
        project=project,
        deployments=deployments,
        pagination=pagination,
        form=form
    )


@bp.route('/projects/<string:project_name>/settings', methods=['GET', 'POST'])
@login_required
@load_project
def project_settings(project):
    # General
    general_form = GeneralForm(data={
        'name': project.name,
        'repo_id': project.repo_id
    })

    if request.method == 'GET' or request.form.get('form_id') == 'general_form':
        if general_form.validate_on_submit():
            if general_form.repo_id.data != project.repo_id:
                try:
                    repo = current_app.github.get_repository(current_user.github_token, general_form.repo_id.data)
                except Exception as e:
                    flash("You do not have access to this repository.")
                project.repo_full_name = repo.get('full_name')
            
            project.name = general_form.name.data
            db.session.commit()
            flash(_('General settings updated.'), 'success')

        if request.headers.get('HX-Request'):
            return render_htmx_partial(
                'projects/partials/settings/_general.html',
                general_form=general_form,
                project=project
            )

    # Environment variables
    env_vars_form = EnvVarsForm(data={
        'env_vars': [
            {'key': env['key'], 'value': env['value']}
            for env in project.env_vars
        ]
    })

    if request.method == 'GET' or request.form.get('form_id') == 'env_vars_form':
        if env_vars_form.validate_on_submit():
            project.env_vars = [
                {'key': entry.key.data, 'value': entry.value.data}
                for entry in env_vars_form.env_vars
            ]
            db.session.commit()
            flash(_('Environment variables updated.'), 'success')

        if request.headers.get('HX-Request'):
            return render_htmx_partial(
                'projects/partials/settings/_env_vars.html',
                env_vars_form=env_vars_form
            )

    # Environments
    prod_environment_form = ProdEnvironmentForm(
        color=project.environments[0].get('color'),
        branch=project.environments[0].get('branch'),
    )
    custom_environment_form = CustomEnvironmentForm(project=project)
    delete_environment_form = DeleteEnvironmentForm(project=project)

    if request.method == 'GET' or request.form.get('form_id') in ('prod_environment_form', 'custom_environment_form', 'delete_environment_form'):
        branches = current_app.github.get_repository_branches(current_user.github_token, project.repo_id)
        prod_environment_form.branch.choices = [(branch['name'], branch['name']) for branch in branches]

    if request.method == 'GET' or request.form.get('form_id') == 'prod_environment_form':
        if prod_environment_form.validate_on_submit():
            project_environments = project.environments.copy()
            project_environments[0] = {
                'color': prod_environment_form.color.data,
                'name': 'Production',
                'slug': 'production',
                'branch': prod_environment_form.branch.data
            }
            project.environments = project_environments
            db.session.commit()
            flash(_('Environment updated.'), 'success')

    if request.method == 'GET' or request.form.get('form_id') == 'custom_environment_form':
        original_slug = request.form.get('original_slug')

        if custom_environment_form.validate_on_submit():
            if original_slug:
                index = next((i for i, env in enumerate(project.environments) 
                            if env['slug'] == original_slug), None)
                project_environments = project.environments.copy()
                project_environments[index] = {
                    'color': custom_environment_form.color.data,
                    'name': custom_environment_form.name.data,
                    'slug': custom_environment_form.slug.data,
                    'branch': custom_environment_form.branch.data
                }
                project.environments = project_environments
                db.session.commit()
                flash(_('Environment updated.'), 'success')
            else:
                project_environments = project.environments.copy()
                project_environments.append({
                    'color': custom_environment_form.color.data,
                    'name': custom_environment_form.name.data,
                    'slug': custom_environment_form.slug.data,
                    'branch': custom_environment_form.branch.data
                })
                project.environments = project_environments
                db.session.commit()
                flash(_('Environment added.'), 'success')

    if request.method == 'GET' or request.form.get('form_id') == 'delete_environment_form':
        if delete_environment_form.validate_on_submit():
            project.environments = [env for env in project.environments if env['slug'] != delete_environment_form.slug.data]
            db.session.commit()
            flash(_('Environment deleted.'), 'success')

    if request.headers.get('HX-Request') and request.form.get('form_id') in ('prod_environment_form', 'custom_environment_form', 'delete_environment_form'):
        return render_htmx_partial(
            'projects/partials/settings/_environments.html',
            project=project,
            prod_environment_form=prod_environment_form,
            custom_environment_form=custom_environment_form,
            delete_environment_form=delete_environment_form,
            colors=COLORS
        )
    
    # Build and deploy
    build_and_deploy_form = BuildAndDeployForm(
        framework=project.config.get('framework'),
        runtime=project.config.get('runtime'),
        use_custom_root_directory=project.config.get('root_directory') is not None,
        root_directory=project.config.get('root_directory'),
        use_custom_build_command=project.config.get('build_command') is not None,
        build_command=project.config.get('build_command'),
        use_custom_pre_deploy_command=project.config.get('pre_deploy_command') is not None,
        pre_deploy_command=project.config.get('pre_deploy_command'),
        use_custom_start_command=project.config.get('start_command') is not None,
        start_command=project.config.get('start_command')
    )

    if request.method == 'GET' or request.form.get('form_id') == 'build_and_deploy_form':
        if build_and_deploy_form.validate_on_submit():
            project.config = {
                'framework': build_and_deploy_form.framework.data,
                'runtime': build_and_deploy_form.runtime.data,
                'root_directory': build_and_deploy_form.root_directory.data,
                'build_command': build_and_deploy_form.build_command.data if build_and_deploy_form.use_custom_build_command.data else None,
                'pre_deploy_command': build_and_deploy_form.pre_deploy_command.data if build_and_deploy_form.use_custom_pre_deploy_command.data else None,
                'start_command': build_and_deploy_form.start_command.data if build_and_deploy_form.use_custom_start_command.data else None
            }
            db.session.commit()
            flash(_('Build & Deploy settings updated.'), 'success')
            
        if request.headers.get('HX-Request'):
          return render_htmx_partial(
              'projects/partials/settings/_build_and_deploy.html',
              build_and_deploy_form=build_and_deploy_form
          )
    
    return render_template(
        'projects/pages/settings.html',
        project=project,
        general_form=general_form,
        prod_environment_form=prod_environment_form,
        custom_environment_form=custom_environment_form,
        delete_environment_form=delete_environment_form,
        build_and_deploy_form=build_and_deploy_form,
        env_vars_form=env_vars_form,
        colors=COLORS
    )


@bp.route('/projects/<string:project_name>/deployments')
@login_required
@load_project
def project_deployments(project):
    form = DeploymentForm()
    if form.validate_on_submit():
        # We retrieve the latest commit from the repo
        branch = project.environments[0].get('branch') if project.environments else None
        commits = current_app.github.get_repository_commits(
            current_user.github_token,
            project.repo_id,
            branch,
            1
        )
        # Error our if no commit (at least one)
        if len(commits) == 0:
            flash(_('No commits found for branch {branch}.'), 'error')
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
        'projects/pages/deployments.html',
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
        'deployments/pages/index.html', 
        project=deployment.project, 
        deployment=deployment,
        logs=deployment.parsed_logs
    )


@bp.app_context_processor
def inject_secondary_nav():
    def get_secondary_nav():
        endpoint = request.endpoint

        if endpoint in ['main.index', 'main.projects', 'main.settings']:
            return 'partials/tabs/_account.html'
        elif endpoint in ['main.project', 'main.project_deployments', 'main.project_settings', 'main.deployment']:
            return 'partials/tabs/_project.html'

        return None
    
    return dict(secondary_nav_template=get_secondary_nav())


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


# TO REMOVE

@bp.route('/kitchen-sink')
def kitchen_sink():
    flash('This is a simple text message.')
    flash('This is a simple text success message.', 'success')
    flash('This is a simple text warning message.', 'warning')
    flash('This is a simple text error message.', 'error')
    flash('This is a simple text error message.', 'info')
    flash({
        'title': 'Structured error',
        'description': 'This is a structured error message with a title, description and action.',
        'action': {
            'label': 'This is a simple text action',
            'url': 'https://google.com',
            'click': 'console.log("Clicked!")'
        }
    }, 'error')
    return render_template('kitchen-sink.html')
