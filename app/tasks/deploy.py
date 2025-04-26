import docker
from app.models import Deployment, Alias
from app import create_app, db
import socket
from contextlib import closing
from datetime import datetime, timezone
import time
from app.helpers.github import get_installation_instance
import requests
import re


def check_port(host, port):
    """Check if a port is open on a host"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def deploy(deployment_id: str):
    """Run the deployment using Docker"""
    app = create_app()
    docker_client = docker.from_env()

    with app.app_context():
        container = None
        deployment = db.session.get(Deployment, deployment_id)
        project = deployment.project
        base_domain = app.config['BASE_DOMAIN']

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

            app.logger.info(f"config: {deployment.config}")

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

            app.logger.info(f"Commands: {commands}")

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
                    "app.deployment_id": deployment.id,
                    "app.project_id": project.id
                }
            )
            docker_client.networks.get("app_internal").connect(container.id)

            # Save the container ID
            deployment.container_id = container.id
            db.session.commit()

            # Wait for the deployment to conclude and save logs as we go
            start_time = time.time()
            timeout = 90
            
            while (time.time() - start_time) < timeout:
                container.reload()
                
                if container.status == 'exited':
                    raise Exception("Container failed to start")
                
                deployment.build_logs = container.logs(
                    stdout=True,
                    stderr=True,
                    timestamps=True
                ).decode('utf-8')
                db.session.commit()
                
                # Check if the app is ready (i.e. listens on port 8000)
                if check_port(container.attrs['NetworkSettings']['Networks']['app_internal']['IPAddress'], 8000):
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
                response = requests.post(
                    'http://openresty/set-alias',
                    json={ branch_hostname: container_name },
                    timeout=2
                )
                response.raise_for_status()
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
                    response = requests.post(
                        'http://openresty/set-alias',
                        json={ env_hostname: container_name },
                        timeout=2
                    )
                    response.raise_for_status()
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
                    response = requests.post(
                        'http://openresty/set-alias',
                        json={ env_hostname: container_name },
                        timeout=2
                    )
                    response.raise_for_status()
                    Alias.update_or_create(
                        subdomain=env_subdomain,
                        deployment_id=deployment.id,
                        type='environment',
                        value=deployment.environment_id
                    )
                except Exception as e:
                    app.logger.error(f"Failed to setup environment domain {env_hostname}: {e}")
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()  # Clear any failed transaction
            deployment.conclusion = 'failed'
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

            db.session.commit()

            app.logger.info(f'Deployment {deployment.id} completed with conclusion: {deployment.conclusion}')
            docker_client.close()