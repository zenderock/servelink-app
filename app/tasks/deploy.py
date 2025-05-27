import docker
from app.models import Deployment, Alias, Project
from app import create_app, db
import socket
from contextlib import closing
from datetime import datetime, timezone
import time
import requests, socket
from app.helpers.github import get_installation_instance
import re
import yaml
import os


def http_probe(ip, port, path="/", timeout=2):
    url = f"http://{ip}:{port}{path}"
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except requests.exceptions.RequestException:
        return False
    

def deploy(deployment_id: str):
    """Run the deployment using Docker"""
    app = create_app()
    docker_client = docker.from_env()

    with app.app_context():
        container = None
        deployment = db.session.get(Deployment, deployment_id)
        project = deployment.project
        base_domain = app.config['BASE_DOMAIN']

        if project.status != 'active':
            app.logger.warning(
                f"Deployment {deployment_id} for project {project.id} ({project.name}) "
                f"will not proceed as project status is '{project.status}'."
            )
            deployment.status = 'skipped'
            deployment.conclusion = 'skipped'
            deployment.build_logs = f"Skipped: Project status is '{project.status}'."
            deployment.concluded_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        try:
            # Mark deployment as in-progress
            deployment.status = 'in_progress'
            db.session.commit()

            # Transform list of env var objects into dict
            env_vars_dict = {
                var['key']: var['value'] 
                for var in (deployment.env_vars or [])
            }
            env_vars_dict['PIP_DISABLE_PIP_VERSION_CHECK'] = '1' # Disable pip version check

            # Prepare commands
            commands = []

            # Step 1: Clone the repository
            commands.append(f"echo 'Cloning {deployment.repo['full_name']} (Branch: {deployment.branch}, Commit: {deployment.commit_sha[:7]})'")
            installation = get_installation_instance(deployment.project.github_installation_id)
            commands.append(
                "git init -q && "
                f"git fetch -q --depth 1 https://x-access-token:{installation.token}@github.com/{deployment.repo['full_name']}.git {deployment.commit_sha} && "
                f"git checkout -q FETCH_HEAD"
            )
            
            # Step 2: Build the project
            commands.append("echo 'Installing dependencies...'")
            commands.append(deployment.config.get('build_command', 'pip install --progress-bar off -r requirements.txt'))

            # Step 3: Run pre-deploy command
            if deployment.config.get('pre_deploy_command'):
                commands.append("echo 'Running pre-deploy command...'")
                commands.append(deployment.config.get('pre_deploy_command'))

            # Step 4: Start Gunicorn
            commands.append(
                "(python -c 'import gunicorn' 2>/dev/null || "
                "(echo 'Installing gunicorn...' && pip install --progress-bar off gunicorn))"
            )
            commands.append("echo 'Starting application...'")
            commands.append(deployment.config.get('start_command', 'gunicorn --log-level warning --bind 0.0.0.0:8000 main:app'))

            # Run the container
            # TODO: Add cache for pip
            container_name = f"runner-{deployment.id[:7]}"
            container = docker_client.containers.run(
                name=container_name,
                image="runner",
                command=["/bin/sh", "-c", " && ".join(commands)],
                environment=env_vars_dict,
                working_dir="/app",
                detach=True,
                network="app_default",
                labels={
                    "traefik.enable": "true",
                    f"traefik.http.routers.deployment-{deployment.id}.rule": f"Host(`{deployment.slug}.{base_domain}`)",
                    f"traefik.http.routers.deployment-{deployment.id}.service": f"deployment-{deployment.id}@docker",
                    f"traefik.http.services.deployment-{deployment.id}.loadbalancer.server.port": "8000",
                    "traefik.docker.network": "app_default",
                    "app.deployment_id": deployment.id,
                    "app.project_id": project.id
                }
            )
            docker_client.networks.get("app_internal").connect(container.id)

            # Save the container ID
            deployment.container_id = container.id
            deployment.container_status = 'running'
            db.session.commit()

            # Wait for the deployment to conclude and save logs as we go
            start_time = time.time()
            timeout = 90
            
            while (time.time() - start_time) < timeout:
                container.reload()
                container_ip = container.attrs['NetworkSettings']['Networks']['app_default']['IPAddress']
                
                if (not container_ip):
                    app.logger.info(f"Container {container.id} not yet assigned an IP address")
                    time.sleep(0.5)
                    continue
                
                if container.status == 'exited':
                    raise Exception("Container failed to start")
                
                deployment.build_logs = container.logs(
                    stdout=True,
                    stderr=True,
                    timestamps=True
                ).decode('utf-8')
                db.session.commit()
                
                # Check if the app is ready (i.e. listens on port 8000)
                if http_probe(container_ip, 8000):
                    deployment.conclusion = 'succeeded'
                    break
                
                time.sleep(0.5)
            else:
                raise Exception("Timeout waiting for application to start")

            # Setup branch domain
            branch = deployment.branch
            sanitized_branch = re.sub(r'[^a-zA-Z0-9-]', '-', branch) # Won't prevent collisions, but good enough
            branch_subdomain = f"{project.slug}-branch-{sanitized_branch}"
            branch_hostname = f"{branch_subdomain}.{base_domain}"

            try:
                Alias.update_or_create(
                    subdomain=branch_subdomain,
                    deployment_id=deployment.id,
                    type='branch',
                    value=branch
                )
            except Exception as e:
                app.logger.error(f"Failed to setup branch alias {branch_hostname}: {e}")

            # Setup environment domain
            if deployment.environment_id == 'prod':
                env_subdomain = project.slug
                env_hostname = f"{env_subdomain}.{base_domain}"
                try:
                    Alias.update_or_create(
                        subdomain=env_subdomain,
                        deployment_id=deployment.id,
                        type='environment',
                        value=deployment.environment_id
                    )
                except Exception as e:
                    app.logger.error(f"Failed to setup production domain {env_hostname}: {e}")
            elif deployment.environment:
                env_subdomain = f"{project.slug}-env-{deployment.environment['slug']}"
                env_hostname = f"{env_subdomain}.{base_domain}"
                try:
                    Alias.update_or_create(
                        subdomain=env_subdomain,
                        deployment_id=deployment.id,
                        type='environment',
                        value=deployment.environment_id
                    )
                except Exception as e:
                    app.logger.error(f"Failed to setup environment domain {env_hostname}: {e}")
            
            db.session.commit()
            
            # Update Traefik config
            project_config_file_path = os.path.join('/traefik_configs', f"project_{project.id}.yml")
            write_config = False
            traefik_config = None
            
            # 1. Fetch all deployment aliases for the project
            project_aliases = db.session.query(Alias)\
                .join(Deployment, Alias.deployment_id == Deployment.id)\
                .filter(Deployment.project_id == project.id)\
                .filter(Deployment.conclusion == 'succeeded')\
                .all()

            # 2. Generate the Traefik config file content
            if project_aliases:
                routers_config = {}
                for alias_obj in project_aliases:
                    router_name = f"router-alias-{alias_obj.id}"
                    routers_config[router_name] = {
                        'rule': f"Host(`{alias_obj.subdomain}.{base_domain}`)",
                        'service': f"deployment-{alias_obj.deployment_id}@docker",
                    }
                
                traefik_config = {'http': {'routers': routers_config}}
                write_config = True

            # 3. Write or delete Traefik config file
            try:
                if write_config and traefik_config:
                    os.makedirs('/traefik_configs', exist_ok=True)
                    with open(project_config_file_path, 'w') as f:
                        yaml.dump(traefik_config, f, sort_keys=False, indent=2)
                    app.logger.info(f"Traefik dynamic config updated for project {project.id} at {project_config_file_path}")
                else:
                    if os.path.exists(project_config_file_path):
                        os.remove(project_config_file_path)
                        app.logger.info(f"Removed Traefik config for project {project.id} from {project_config_file_path} (no active/valid aliases).")
                    else:
                        app.logger.info(f"No Traefik config to remove for project {project.id} (no active/valid aliases and file doesn't exist).")
            except Exception as e_file_op:
                app.logger.error(f"Error during Traefik config file operation for project {project.id}: {e_file_op}", exc_info=True)
                

            # Cleanup inactive deployments
            try:
                app.deployment_queue.enqueue(
                    'app.tasks.cleanup.cleanup_inactive_deployments',
                    project.id
                )
                app.logger.info(f"Enqueued cleanup_inactive_deployments for project {project.id}.")
            except Exception as e_enqueue:
                app.logger.error(f"Failed to enqueue cleanup_inactive_deployments for project {project.id}: {e_enqueue}")

        except Exception as e:
            db.session.rollback()
            deployment.conclusion = 'failed'
            if deployment.container_status:
                deployment.container_status = 'stopped'
            app.logger.error(f"Deployment {deployment_id} failed: {e}", exc_info=True)
            
        finally:
            # If the deployment succeeded, log a final message
            if deployment.conclusion == 'succeeded':
                container.exec_run(f"sh -c \"echo 'Deployment succeeded. Visit {deployment.url}' >> /proc/1/fd/1\"")
            
            # Update the deployment & project in the DB
            project.updated_at = datetime.now(timezone.utc)
            deployment.status = 'completed'
            deployment.concluded_at = datetime.now(timezone.utc)
            if container:
                deployment.build_logs = container.logs(
                    stdout=True,
                    stderr=True,
                    timestamps=True,
                ).decode('utf-8')

                # If deployment failed and container exists, try to stop and remove it
                if deployment.conclusion == 'failed':
                    try:
                        app.logger.info(f"Attempting to stop and remove failed container {container.id} for deployment {deployment.id}")
                        container.stop()
                        container.remove()
                        deployment.container_status = 'removed'
                        app.logger.info(f"Successfully stopped and removed failed container {container.id}")
                    except docker.errors.NotFound:
                        app.logger.warning(f"Failed container {container.id} for deployment {deployment.id} not found during cleanup.")
                    except Exception as e_clean:
                        app.logger.error(f"Error cleaning up failed container {container.id} for deployment {deployment.id}: {e_clean}", exc_info=True)

            db.session.commit()

            app.logger.info(f'Deployment {deployment.id} completed with conclusion: {deployment.conclusion}')
            docker_client.close()