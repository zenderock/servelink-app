import docker
from app.models import Deployment
from app import create_app, db
from dotenv import load_dotenv
from docker.types import LogConfig


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

            # Log to Fluent Bit
            log_config = LogConfig(
                type='fluentd',
                config={
                    'fluentd-address': 'fluent-bit:24224',
                    'tag': 'runner'
                }
            )

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
                },
                log_config=log_config
            )
            docker_client.networks.get("app_default").connect(container.id)
            
            

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