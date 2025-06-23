from flask import render_template, redirect, url_for, flash, current_app, request, make_response
from flask_babel import _
from flask_login import login_required, current_user
from app import db
from app.main import bp
from app.models import Project, Deployment
from sqlalchemy import select
from app.main.forms import ProjectForm, DeployForm, EnvironmentForm, EnvVarsForm, BuildAndDeployForm, GeneralForm, DeleteEnvironmentForm, DeleteProjectForm
from app.tasks.deploy import deploy
from app.helpers.github import get_installation_instance
from app.main.decorators import load_project, load_deployment
from app.helpers.colors import COLORS
from app.helpers.htmx import render_htmx_partial
import os
from datetime import datetime, timezone
from app.helpers.environments import group_branches_by_environment
from app.utils.token import generate_token


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():

    projects = db.session.scalars(
        select(Project)
        .where(
            Project.user_id == current_user.id,
            Project.status != 'deleted'
        )
        .order_by(Project.updated_at.desc())
        .limit(6)
    ).all()
    
    deployments = db.session.scalars(
        select(Deployment)
        .join(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Deployment.created_at.desc())
        .limit(10)
    ).all()
    
    return render_template(
        'pages/index.html',
        projects=projects,
        deployments=deployments
    )


@bp.route('/repo-select')
@login_required
def repo_select():
    accounts = []
    selected_account = None
    try:
        installations = current_app.github.get_user_installations(current_user.github_token)
        accounts = [installation['account']['login'] for installation in installations]
        selected_account = request.args.get('account') or (accounts[0] if accounts else None)
    except Exception as e:
        current_app.logger.error(f"Error fetching installations: {str(e)}")
        flash(_('Error fetching installations from GitHub.'), 'error')
    
    return render_template(
        'projects/partials/_repo-select.html',
        accounts=accounts,
        selected_account=selected_account
    )


@bp.route('/new-project', methods=['GET', 'POST'])
@login_required
def new_project():
    return render_template('projects/pages/new/repo.html')


@bp.route('/new-project/details', methods=['GET', 'POST'])
@login_required
def new_project_details():
    repo_id = request.args.get('repo_id')
    repo_owner = request.args.get('repo_owner')
    repo_name = request.args.get('repo_name')
    repo_default_branch = request.args.get('repo_default_branch')
    
    if not repo_id or not repo_owner or not repo_name or not repo_default_branch:
        flash(_('Missing repository details.'), 'error')
        return redirect(url_for('main.new_project'))
    
    defaults = {
        'repo_id': repo_id,
        'name': repo_name,
        'production_branch': repo_default_branch
    }
    form = ProjectForm(request.form or None, **defaults)
    
    if form.validate_on_submit():
        # Make sure the repo suggested is accessible to the user
        try:
            repo = current_app.github.get_repository(current_user.github_token, repo_id)
        except Exception as e:
            flash("You do not have access to this repository.")
            return redirect(url_for('main.new_project'))

        installation = current_app.github.get_repository_installation(repo.get('full_name'))
        # Get the installation instance as this force create/update the token
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
                'root_directory': form.root_directory.data if form.use_custom_root_directory.data else None,
                'build_command': form.build_command.data if form.use_custom_build_command.data else None,
                'pre_deploy_command': form.pre_deploy_command.data if form.use_custom_pre_deploy_command.data else None,
                'start_command': form.start_command.data if form.use_custom_start_command.data else None
            },
            env_vars=env_vars,
            environments=[{
                'id': 'prod',
                'color': 'blue',
                'name': 'Production',
                'slug': 'production',
                'branch': form.production_branch.data,
                'status': 'active'
            }],
            user=current_user
        )
        db.session.add(project)
        db.session.commit()
        flash(_('Project added.'), 'success')
        return redirect(url_for('main.project', project_name=project.name))

    return render_template(
        'projects/pages/new/details.html',
        form=form,
        repo_full_name=f"{repo_owner}/{repo_name}",
        frameworks=current_app.frameworks,
        environments=[{
            'color': 'blue',
            'name': 'Production',
            'slug': 'production'
        }]
    )


@bp.route('/settings')
@login_required
def settings():
    return render_template(
        'pages/settings.html'
    )


@bp.route('/projects')
@login_required
def projects():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    query = select(Project).where(
        Project.user_id == current_user.id,
        Project.status != 'deleted'
    ).order_by(Project.updated_at.desc())

    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )
    projects = pagination.items

    return render_template(
        'pages/projects.html',
        projects=projects,
        pagination=pagination,
    )


@bp.route('/projects/<string:project_name>')
@login_required
@load_project
def project(project):
    fragment = request.args.get('fragment')

    bearer_token = generate_token(
        secret_key=current_app.config['SECRET_KEY'],
        payload={
            'pid': project.id,
            'uid': current_user.id
        }
    )

    if request.headers.get('HX-Request') and fragment == 'sse':
        return render_htmx_partial(
            'projects/partials/_index_sse.html',
            project=project,
            bearer_token=bearer_token
        )

    deployments = db.session.scalars(
        project.deployments
        .select()
        .order_by(Deployment.created_at.desc())
        .limit(10)
    ).all()
    
    env_aliases = project.get_environment_aliases()

    if request.headers.get('HX-Request') and fragment == 'deployments':
        return render_htmx_partial(
            'projects/partials/_index_deployments.html',
            project=project,
            deployments=deployments,
            env_aliases=env_aliases
        )

    return render_template(
        'projects/pages/index.html',
        project=project,
        deployments=deployments,
        apps_base_domain=current_app.config['APPS_BASE_DOMAIN'],
        env_aliases=env_aliases,
        bearer_token=bearer_token
    )


@bp.route('/projects/<string:project_name>/deploy', methods=['GET', 'POST'])
@login_required
@load_project
def project_deploy(project):
    deployment_form = DeployForm(project)

    environment_choices = []
    for env in project.active_environments:
        environment_choices.append((env['slug'], env['name']))
    deployment_form.environment_slug.choices = environment_choices

    if deployment_form.validate_on_submit():
        try:
            environment = project.get_environment_by_slug(deployment_form.environment_slug.data)
            branch, commit_sha = deployment_form.commit.data.split(':')
            commit = current_app.github.get_repository_commit(
                user_access_token=current_user.github_token,
                repo_id=project.repo_id,
                commit_sha=commit_sha,
                branch=branch
            )
        
            deployment = Deployment(
                project=project,
                environment_id=environment.get('id'),
                trigger='user',
                branch=branch,
                commit_sha=commit['sha'],
                commit_meta={
                    'author': commit['author']['login'],
                    'message': commit['commit']['message'],
                    'date': datetime.fromisoformat(commit['commit']['author']['date'].replace('Z', '+00:00')).isoformat()
                },
            )
            db.session.add(deployment)
            db.session.commit()

            current_app.redis_client.xadd(
                f"stream:project:{project.id}:updates",
                fields = {
                   "event_type": "deployment_created",
                    "project_id": project.id,
                    "deployment_id": deployment.id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )
            
            current_app.deployment_queue.enqueue(deploy, deployment.id)
            current_app.logger.info(
                f'Deployment {deployment.id} created and queued for '
                f'project {project.name} ({project.id}) to environment {environment.get('slug')}'
            )

            if request.headers.get('HX-Request'):
                return '', 200, { 'HX-Redirect': url_for('main.deployment', project_name=project.name, deployment_id=deployment.id) }
            else:
                return redirect(url_for('main.deployment', project_name=project.name, deployment_id=deployment.id))
            
        except Exception as e:
            current_app.logger.error(f"Error deploying {project.name}: {str(e)}")
            flash(_('Failed to deploy: %(error)s', error=str(e)), 'error')
            if request.headers.get('HX-Request'):
                return render_template('layouts/fragment.html') # TODO: FIX OOB

    return render_template(
        'projects/partials/_deploy-dialog-content.html',
        project=project,
        deployment_form=deployment_form
    )


@bp.route('/projects/<string:project_name>/environments/<string:environment_slug>/commits', methods=['GET'])
@login_required
@load_project
def project_environment_commits(project, environment_slug):
    commits = []
    environment = project.get_environment_by_slug(environment_slug)
    if not environment:
        flash(_('Environment not found.'), 'error')
    else:
        # Get all branch names for this repo
        try:
            branches = current_app.github.get_repository_branches(current_user.github_token, project.repo_id)
            branch_names = [branch['name'] for branch in branches]
        except Exception as e:
            current_app.logger.error(f"Error fetching branches: {str(e)}")
            flash(_('Error fetching branches from GitHub.'), 'error')
            return render_htmx_partial(
                'projects/partials/_environment_commits.html',
                project=project,
                commits=[]
            )
        
        # Find branches that match this environment
        branches_by_environment = group_branches_by_environment(project.active_environments, branch_names)
        matching_branches = branches_by_environment.get(environment['slug'])
        
        # Get the latest 5 commits for each matching branch
        commits = []
        for branch in matching_branches:
            try:
                branch_commits = current_app.github.get_repository_commits(
                    current_user.github_token,
                    project.repo_id,
                    branch,
                    per_page=5
                )
                
                # Add branch information to each commit
                for commit in branch_commits:
                    commit['branch'] = branch
                    commits.append(commit)
            except Exception as e:
                flash(_('Error fetching commits for branch {}: {}').format(branch, str(e)), 'warning')
                continue
        
        # Sort commits by date (newest first)
        commits.sort(key=lambda x: x['commit']['author']['date'], reverse=True)
    
    return render_htmx_partial(
        'projects/partials/_environment_commits.html',
        project=project,
        commits=commits[:5]
    )


@bp.route('/projects/<string:project_name>/settings', methods=['GET', 'POST'])
@bp.route('/projects/<string:project_name>/settings/<string:fragment>', methods=['GET', 'POST'])
@login_required
@load_project
def project_settings(project, fragment=None):
    # Delete project
    delete_project_form = DeleteProjectForm(data={'project_name': project.name})
    if request.method == 'POST' and 'delete_project' in request.form:
        if delete_project_form.validate_on_submit():
            try:
                project.status = 'deleted'
                db.session.commit()

                # Project is mark as deleted, actual cleanup is delegated to a job
                current_app.deployment_queue.enqueue(
                    'app.tasks.cleanup.cleanup_project',
                    project.id,
                    job_timeout='1h'
                )
                
                flash(_('Project "%(name)s" has been marked for deletion.', name=project.name), 'success')
                return redirect(url_for('main.index'))
            except Exception as e:
                db.session.rollback()
                flash(_('An error occurred while marking the project for deletion.'), 'error')
                current_app.logger.error(f"Error marking project {project.name} as deleted: {str(e)}")

        for error in delete_project_form.confirm.errors:
            flash(error, 'error')
        return redirect(url_for('main.project_settings', project_name=project.name, _anchor='danger'))

    # General
    general_form = GeneralForm(data={
        'name': project.name,
        'repo_id': project.repo_id
    })

    if (request.method == 'GET' and not fragment) or fragment == 'general':
        if general_form.validate_on_submit():
            # Name
            old_name = project.name
            project.name = general_form.name.data

            # Repo
            if general_form.repo_id.data != project.repo_id:
                try:
                    repo = current_app.github.get_repository(current_user.github_token, general_form.repo_id.data)
                except Exception as e:
                    flash("You do not have access to this repository.")
                project.repo_id = general_form.repo_id.data
                project.repo_full_name = repo.get('full_name')
            
            # Avatar upload
            avatar_file = general_form.avatar.data
            current_app.logger.info(f"Avatar file: {avatar_file}")
            if avatar_file and hasattr(avatar_file, 'filename') and avatar_file.filename:
                try:
                    from PIL import Image
                    
                    avatar_dir = os.path.join(current_app.config['UPLOAD_DIR'], 'avatars')
                    os.makedirs(avatar_dir, exist_ok=True)
                    
                    target_filename = f"project_{project.id}.webp"
                    target_filepath = os.path.join(avatar_dir, target_filename)
                    
                    img = Image.open(avatar_file)
                        
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                        
                    max_size = (512, 512)
                    img.thumbnail(max_size)
                    
                    img.save(target_filepath, 'WEBP', quality=85)
                    
                    project.avatar_updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                except Exception as e:
                    flash(_('Error processing avatar: {}'.format(str(e))), 'error')
            
            # Avatar deletion
            if general_form.delete_avatar.data:
                avatar_dir = os.path.join(current_app.config['UPLOAD_DIR'], 'avatars')
                filename = f"project_{project.id}.webp"
                filepath = os.path.join(avatar_dir, filename)
                
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                project.avatar_updated_at = None
            
            db.session.commit()
            flash(_('General settings updated.'), 'success')

            # Redirect if the name has changed
            if old_name != project.name:
                new_url = url_for('main.project_settings', project_name=project.name)
                
                if request.headers.get('HX-Request'):
                    response = make_response()
                    response.headers['HX-Redirect'] = new_url
                    return response
                else:
                    return redirect(new_url)

        if request.headers.get('HX-Request'):
            return render_htmx_partial(
                'projects/partials/settings/_general.html',
                general_form=general_form,
                project=project
            )

    # Environment variables
    env_vars_form = EnvVarsForm(data={
        'env_vars': [
            {
                'key': env.get('key', ''),
                'value': env.get('value', ''),
                'environment': env.get('environment', '')
            }
            for env in project.env_vars
        ]
    })

    environment_choices = [('', _('All environments'))]
    for env in project.environments:
        environment_choices.append((env['slug'], env['name']))
        
    for env_var_form in env_vars_form.env_vars:
        env_var_form.environment.choices = environment_choices

    if (request.method == 'GET' and not fragment) or fragment == 'env_vars':
        if env_vars_form.validate_on_submit():
            project.env_vars = [
                {
                    'key': entry.key.data,
                    'value': entry.value.data,
                    'environment': entry.environment.data
                }
                for entry in env_vars_form.env_vars
            ]
            db.session.commit()
            flash(_('Environment variables updated.'), 'success')

        if request.headers.get('HX-Request'):
            return render_htmx_partial(
                'projects/partials/settings/_env_vars.html',
                env_vars_form=env_vars_form,
                project=project
            )

    # Environmentse
    environment_form = EnvironmentForm(project=project)
    delete_environment_form = DeleteEnvironmentForm(project=project)
    environments_updated = False

    if (request.method == 'GET' and not fragment) or fragment == 'environment':
        if environment_form.validate_on_submit():
            try:
                if environment_form.environment_id.data:
                    # Update existing environment using ID
                    environment_id = environment_form.environment_id.data
                    env = project.get_environment_by_id(environment_id)
                    
                    if env:
                        updates = {
                            'color': environment_form.color.data,
                            'name': environment_form.name.data,
                            'slug': environment_form.slug.data,
                            'branch': environment_form.branch.data
                        }
                        
                        project.update_environment(environment_id, **updates)
                        db.session.commit()
                        flash(_('Environment updated.'), 'success')
                        environments_updated = True
                    else:
                        flash(_('Environment not found.'), 'error')
                else:
                    # Create new environment
                    if env := project.create_environment(
                        name=environment_form.name.data,
                        slug=environment_form.slug.data,
                        color=environment_form.color.data,
                        branch=environment_form.branch.data
                    ):
                        db.session.commit()
                        flash(_('Environment added.'), 'success')
                        environments_updated = True
                    else:
                        flash(_('Failed to create environment.'), 'error')
            except ValueError as e:
                flash(str(e), 'error')

    if (request.method == 'GET' and not fragment) or fragment == 'delete_environment':
        if delete_environment_form.validate_on_submit():
            try:
                if project.delete_environment(delete_environment_form.environment_id.data):
                    db.session.commit()
                    flash(_('Environment deleted.'), 'success')
                    environments_updated = True
                else:
                    flash(_('Environment not found.'), 'error')
            except ValueError as e:
                flash(str(e), 'error')

    if request.headers.get('HX-Request') and fragment in ('environment', 'delete_environment'):
        return render_htmx_partial(
            'projects/partials/settings/_environments.html',
            project=project,
            environment_form=environment_form,
            delete_environment_form=delete_environment_form,
            colors=COLORS,
            updated=environments_updated
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

    if (request.method == 'GET' and not fragment) or fragment == 'build_and_deploy':
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
              project=project,
              build_and_deploy_form=build_and_deploy_form,
              frameworks=current_app.frameworks
          )
    
    return render_template(
        'projects/pages/settings.html',
        project=project,
        general_form=general_form,
        environment_form=environment_form,
        delete_environment_form=delete_environment_form,
        build_and_deploy_form=build_and_deploy_form,
        env_vars_form=env_vars_form,
        delete_project_form=delete_project_form,
        colors=COLORS,
        frameworks=current_app.frameworks
    )


@bp.route('/projects/<string:project_name>/deployments')
@login_required
@load_project
def project_deployments(project):
    fragment = request.args.get('fragment')

    bearer_token = generate_token(
        secret_key=current_app.config['SECRET_KEY'],
        payload={
            'pid': project.id,
            'uid': current_user.id
        }
    )

    if request.headers.get('HX-Request') and fragment == 'sse':
        return render_template(
            'projects/partials/_deployments_sse.html',
            project=project,
            bearer_token=bearer_token
        )

    env_aliases = project.get_environment_aliases()
    
    page = request.args.get('page', 1, type=int)
    per_page = 25
    
    query = project.deployments.select().order_by(Deployment.created_at.desc())
    
    # Filter by environment
    if environment_slug := request.args.get('environment'):
        environment = project.get_environment_by_slug(environment_slug)
        if environment:
            query = query.where(Deployment.environment_id == environment['id'])
    
    # Filter by status (conclusion)
    if status := request.args.get('status'):
        if status == 'in_progress':
            query = query.where(Deployment.conclusion == None)
        else:
            query = query.where(Deployment.conclusion == status)
    
    # Filter by date range
    if date_from := request.args.get('date-from'):
        try:
            from_date = datetime.fromisoformat(date_from)
            query = query.where(Deployment.created_at >= from_date)
        except ValueError:
            pass
            
    if date_to := request.args.get('date-to'):
        try:
            to_date = datetime.fromisoformat(date_to)
            query = query.where(Deployment.created_at <= to_date)
        except ValueError:
            pass
    
    # Filter by branch
    if branch := request.args.get('branch'):
        query = query.where(Deployment.branch == branch)

    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )
    deployments = pagination.items

    if request.headers.get('HX-Request') and fragment == 'deployments':
        return render_htmx_partial(
            'projects/partials/_deployments.html',
            project=project,
            deployments=deployments,
            pagination=pagination,
            env_aliases=env_aliases
        )
    
    branches = db.session.query(
        Deployment.branch
    ).filter(
        Deployment.project_id == project.id
    ).distinct().all()
    branches = [{'name': b.branch, 'value': b.branch} for b in branches if b.branch]

    return render_template(
        'projects/pages/deployments.html',
        project=project,
        deployments=deployments,
        pagination=pagination,
        branches=branches,
        env_aliases=env_aliases,
        bearer_token=bearer_token
    )


@bp.route('/projects/<string:project_name>/deployments/<string:deployment_id>')
@login_required
@load_project
@load_deployment
def deployment(project, deployment):
    fragment = request.args.get('fragment')

    bearer_token = generate_token(current_app.config['SECRET_KEY'], {
        'did': deployment.id,
        'pid': project.id,
        'uid': current_user.id
    })

    if request.headers.get('HX-Request') and fragment == 'status-sse':
        return render_htmx_partial(
            'deployments/partials/_status-sse.html',
            project=project,
            deployment=deployment,
            bearer_token=bearer_token
        )
    
    if request.headers.get('HX-Request') and fragment == 'logs-sse':
        return render_htmx_partial(
            'deployments/partials/_logs-sse.html',
            project=project,
            deployment=deployment,
            bearer_token=bearer_token
        )
    
    env_aliases = project.get_environment_aliases()

    if request.headers.get('HX-Request') and fragment == 'header':
        return render_htmx_partial(
            'deployments/partials/_header.html',
            project=project,
            deployment=deployment,
            env_aliases=env_aliases
        )

    return render_template(
        'deployments/pages/index.html', 
        project=project,
        deployment=deployment,
        env_aliases=env_aliases,
        bearer_token=bearer_token
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
        if current_project:
            query = select(Project).where(
                Project.status != 'deleted',
                Project.id != current_project.id
            )
        else:
            query = select(Project).where(Project.status != 'deleted')
        
        return db.session.scalars(
            query.order_by(Project.updated_at.desc())
            .limit(5)
        ).all()

    return dict(get_latest_projects=get_latest_projects)


@bp.app_context_processor
def inject_latest_deployments():
    def get_latest_deployments(current_deployment=None):
        query = Deployment.query
        if current_deployment:
            query = query.filter(Deployment.id != current_deployment.id)            
            
        return query.order_by(Deployment.created_at.desc()).limit(4).all()

    return dict(get_latest_deployments=get_latest_deployments)