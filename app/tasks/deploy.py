import docker
from app.models import Deployment
from app import create_app, db
import socket
from contextlib import closing
from datetime import datetime, timezone
import time
from app.helpers.github import get_installation_instance


def check_port(host, port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0
    

def deploy(deployment_id: str):
    """Run the deployment using Docker"""
    app = create_app()
    with app.app_context():
        container = None
        deployment = db.session.get(Deployment, deployment_id)

        try:
            # Initialize Docker client
            docker_client = docker.from_env()

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

            # Start the container
            # TODO: Add cache for pip
            container = docker_client.containers.run(
                image="runner",
                command=["/bin/sh", "-c", " && ".join(commands)],
                environment=env_vars_dict,
                working_dir="/app",
                detach=True,
                network="app_default",
                labels={
                    "traefik.enable": "true",
                    f"traefik.http.routers.{deployment.id}.rule": f"Host(`{deployment.id}.{app.config.get('BASE_DOMAIN')}`)",
                    f"traefik.http.services.{deployment.id}.loadbalancer.server.port": "8000",
                    "app.deployment_id": deployment.id,
                    "app.project_id": deployment.project_id
                }
            )
            docker_client.networks.get("app_internal").connect(container.id)

            # Save the container ID in the deployment
            deployment.container_id = container.id
            db.session.commit()
            
            # Wait for either container exit or port availability (up to 30 seconds)
            max_retries = 30
            for i in range(max_retries):
                container.reload()  # Refresh container state
                
                if container.status == 'exited':
                    # Container failed to start
                    logs = container.logs().decode('utf-8')
                    raise Exception(f"Container failed to start:\n{logs}")
                
                # Check if port 8000 is responding
                if check_port(container.attrs['NetworkSettings']['Networks']['app_internal']['IPAddress'], 8000):
                    deployment.conclusion = 'succeeded'
                    break
                    
                if i < max_retries - 1:
                    time.sleep(1)
            else:
                raise Exception("Timeout waiting for application to start")
            
        except Exception as e:
            deployment.conclusion = 'failed'
            app.logger.error(f"Deployment {deployment_id} failed: {e}")

        finally:
            if deployment.conclusion == 'succeeded':
                container.exec_run(f"sh -c \"echo 'Deployment succeeded. Visit {deployment.url()}' >> /proc/1/fd/1\"")

            deployment.status = 'completed'
            deployment.concluded_at = datetime.now(timezone.utc)
            deployment.build_logs = container.logs(
                stdout=True,
                stderr=True,
                timestamps=True,
            ).decode('utf-8')
            db.session.commit()

            app.logger.info(f'Deployment {deployment.id} completed with conclusion: {deployment.conclusion}')

            # TODO: remove the container if needed