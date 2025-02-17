from flask import Flask
import docker
from app.models import Deployment
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
    

def setup_domain(deployment_id: str, subdomain: str, base_domain: str, service_name: str, priority: int = 50):
    """
    Setup a domain in Traefik for a deployment
    Returns the Traefik API response
    Raises an exception if the request fails
    """
    router_config = {
        "entryPoints": ["web", "websecure"],
        "rule": f"Host(`{subdomain}.{base_domain}`)",
        "service": service_name,
        "priority": priority
    }
    
    response = requests.put(
        f"http://traefik:8080/api/providers/rest/routers/{subdomain}",
        json=router_config,
        timeout=2
    )
    response.raise_for_status()
    return response.json()


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
            deployment.slug = f"{project.slug}-{deployment.id[:7]}.{base_domain}"
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
            commands.append(f"echo 'Cloning {deployment.repo['full_name']} (Branch: {deployment.repo['branch']}, Commit: {deployment.commit['sha'][:7]})'")
            installation = get_installation_instance(deployment.project.github_installation_id)
            commands.append(
                "git init -q && "
                f"git fetch -q --depth 1 https://x-access-token:{installation.token}@github.com/{deployment.repo['full_name']}.git {deployment.commit['sha']} && "
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
            container_name = f"runner-{deployment.id}"
            container = docker_client.containers.run(
                name=container_name,
                image="runner",
                command=["/bin/sh", "-c", " && ".join(commands)],
                environment=env_vars_dict,
                working_dir="/app",
                detach=True,
                network="app_default",
                labels={
                    # "traefik.enable": "true",
                    # f"traefik.http.routers.{deployment.id}.rule": (
                    #     f"Host(`{deployment.slug}`)"
                    # ),
                    # f"traefik.http.services.{deployment.id}.loadbalancer.server.port": "8000",
                    "app.deployment_id": deployment.id,
                    "app.project_id": project.id
                }
            )
            docker_client.networks.get("app_internal").connect(container.id)

            # Save the container ID
            deployment.container_id = container.id
            db.session.commit()

            # Register the service in Traefik
            service_name = f"service-{deployment.id}"
            service_config = {
                "loadBalancer": {
                    "servers": [{"url": f"http://{container_name}:8000"}]
                }
            }
            service_response = requests.put(
                f"http://traefik:8080/api/providers/rest/configuration/http/services/{service_name}",
                json=service_config,
                timeout=2
            )
            service_response.raise_for_status()

            # Setup branch domain
            branch = deployment.commit['branch']
            sanitized_branch = re.sub(r'[^a-zA-Z0-9-]', '-', branch) # Won't prevent collisions, but good enough
            branch_subdomain = f"{project.slug}-branch-{sanitized_branch}"
            
            try:
                setup_domain(deployment.id, branch_subdomain, base_domain, service_name, priority=50)
                project.mapping["branches"][branch] = deployment.id
            except Exception as e:
                app.logger.error(f"Failed to setup branch domain {branch_subdomain}: {e}")
            
            # Setup environment domain
            if deployment.environment == 'production':
                env_subdomain = project.slug
                try:
                    setup_domain(deployment.id, env_subdomain, base_domain, service_name, priority=100)
                    project.mapping["environments"]["production"] = deployment.id
                except Exception as e:
                    app.logger.error(f"Failed to setup production domain {env_subdomain}: {e}")
            elif deployment.environment not in ['preview', None]:
                env_subdomain = f"{project.slug}-env-{deployment.environment}"
                try:
                    setup_domain(deployment.id, env_subdomain, base_domain, service_name, priority=75)
                    project.mapping["environments"][deployment.environment] = deployment.id
                except Exception as e:
                    app.logger.error(f"Failed to setup environment domain {env_subdomain}: {e}")
            
            db.session.commit()

            # Save the build logs as we go until the deployment concludes
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
            
        except Exception as e:
            deployment.conclusion = 'failed'
            app.logger.error(f"Deployment {deployment_id} failed: {e}")

        finally:
            # If the deployment succeeded, log a final message
            if deployment.conclusion == 'succeeded':
                container.exec_run(f"sh -c \"echo 'Deployment succeeded. Visit {deployment.url()}' >> /proc/1/fd/1\"")

            # Update the deployment in the DB
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