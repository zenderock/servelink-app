import docker
from app.models import Deployment
from app import create_app, db
from dotenv import load_dotenv
import time


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

            # Get cache volume if it exists, otherwise create it
            # TODO: Probably best to make it unique per deployment and copy it over from the previous deployment
            # cache_volume = f"build-cache-{deployment.project_id}"
            # try:
            #     docker_client.volumes.get(cache_volume)
            #     print("Found existing build cache")
            # except docker.errors.NotFound:
            #     docker_client.volumes.create(cache_volume)
            #     print("Created new build cache")

            # Start the container
            container = docker_client.containers.run(
                image="runner",
                command="tail -f /dev/null",
                environment=env_vars_dict,
                # volumes={
                #     cache_volume: {
                #         'bind': '/root/.cache/pip',
                #         'mode': 'rw'
                #     }
                # },
                working_dir="/app",
                detach=True,
                network="app_internal",
                labels={
                    "traefik.enable": "true",
                    f"traefik.http.routers.{deployment.id}.rule": f"Host(`{deployment.id}.{app.config['BASE_DOMAIN']}`)",
                    f"traefik.http.services.{deployment.id}.loadbalancer.server.port": "8000",
                    "app.deployment_id": deployment.id,
                    "app.project_id": deployment.project_id
                }
            )
            docker_client.networks.get("app_default").connect(container.id)

            # Helper function to run commands in the container
            def run_step(cmd: str, message: str, subdir: str = None) -> tuple[bool, str, int]:
                """Runs a shell command in the container, returning (success, logs, duration)."""
                start_time = time.time()

                # cd into subdir if provided, then run the command
                shell_cmd = f'printf "%s\\n" "{message}"'
                if subdir:
                    shell_cmd += f" && cd {subdir}"
                shell_cmd += f" && {cmd}"
                exit_code, output = container.exec_run(
                    ["/bin/sh", "-c", shell_cmd]
                )

                decoded_logs = output.decode("utf-8", errors="replace")
                print(decoded_logs, end="")
                duration = round((time.time() - start_time) * 1000)

                return (exit_code == 0, decoded_logs, duration)

            # Clone the repository
            success, output, duration = run_step(
                f"git clone --depth 1 --branch {deployment.repo['branch']} https://github.com/{deployment.repo['full_name']}.git /app",
                f"Cloning {deployment.repo['full_name']} (Branch: {deployment.repo['branch']}, Commit: {deployment.commit_sha[:7]})"
            )
            print(f"Cloning completed: {duration:.3f}ms")
            if not success:
                raise Exception(f"Clone failed:\n{output}")
            
            # Building project
            success, output, duration = run_step(
                deployment.config.value.get('build_command', 'pip install -r requirements.txt'),
                "Building project...",
                deployment.config.value.get('root_directory')
            )
            if not success:
                raise Exception(f"Build command failed:\n{output}")

            # Run pre-deploy command
            if deployment.config.value.get('pre_deploy_command'):
                success, output, duration = run_step(
                    deployment.config.value.get('pre_deploy_command'),
                    "Running pre-deploy command...",
                    deployment.config.value.get('root_directory')
                )
                if not success:
                    raise Exception(f"Pre-deploy command failed:\n{output}")
                    
            # Start Gunicorn in background
            success, output, duration = run_step(
                (deployment.config.value.get('start_command', 'gunicorn --bind 0.0.0.0:8000 main:app')) + ' &',
                "Starting the app...",
                deployment.config.value.get('root_directory')
            )
            if not success:
                raise Exception(f"Start command failed:\n{output}")
            
            # Wait for Gunicorn to start (up to 10 seconds)
            # max_retries = 10
            # for i in range(max_retries):
            #     code, _ = container.exec_run("nc -z localhost 8000")
            #     if code == 0:
            #         break
            #     if i < max_retries - 1:
            #         time.sleep(1)
            # else:
            #     raise Exception("Gunicorn did not come up on port 8000 - deployment failed.")

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