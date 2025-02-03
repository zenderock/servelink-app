import docker
from app.models import Deployment
from app import create_app, db
from dotenv import load_dotenv
import socket
from contextlib import closing
import time


def check_port(host, port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0
    

def deploy(deployment_id: str):
    """Run the deployment using Docker"""
    load_dotenv()
    
    app = create_app()
    with app.app_context():
        docker_client = docker.from_env()
        container = None
        deployment = db.session.get(Deployment, deployment_id)

        try:
            # Mark deployment as in-progress
            deployment.status = 'in_progress'
            db.session.commit()

            # Transform list of env var objects into dict
            env_vars_dict = {
                var['key']: var['value'] 
                for var in (deployment.env_vars.value or [])
            }

            # Prepare commands
            commands = [ "echo 'Starting deployment...'" ]

            # Step 1: Clone the repository
            commands.append(f"git clone --depth 1 --branch {deployment.repo['branch']} https://github.com/{deployment.repo['full_name']}.git /app")
            
            # Step 2: Build the project
            commands.append(deployment.config.value.get('build_command', 'pip install -r requirements.txt'))

            # Step 3: Run pre-deploy command
            if deployment.config.value.get('pre_deploy_command'):
                commands.append(deployment.config.value.get('pre_deploy_command'))

            # Step 4: Start Gunicorn
            commands.append(deployment.config.value.get('start_command', 'gunicorn --bind 0.0.0.0:8000 main:app'))

            # Start the container
            # TODO: Add cache for pip
            container = docker_client.containers.run(
                image="runner",
                command=["/bin/sh", "-c", " && ".join(commands)],
                environment=env_vars_dict,
                working_dir="/app",
                detach=True,
                network="app_internal",
                labels={
                    "traefik.enable": "true",
                    f"traefik.http.routers.{deployment.id}.rule": f"Host(`{deployment.id}.{app.config.get('BASE_DOMAIN')}`)",
                    f"traefik.http.services.{deployment.id}.loadbalancer.server.port": "8000",
                    "app.deployment_id": deployment.id,
                    "app.project_id": deployment.project_id
                }
            )
            docker_client.networks.get("app_default").connect(container.id)
            
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
                    print("Application is up and running")
                    break
                    
                if i < max_retries - 1:
                    time.sleep(1)
            else:
                raise Exception("Timeout waiting for application to start")

            # Mark deployment as completed
            deployment.status = 'completed'
            deployment.conclusion = 'succeeded'
            db.session.commit()

        except Exception as e:
            # Mark deployment as failed
            deployment.status = 'completed'
            deployment.conclusion = 'failed'
            db.session.commit()
            print(f"Deployment {deployment_id} failed: {e}")

            # Clean up the container
            if container:
                container.remove(force=True)