from app import create_app, db
from app.models import Project, Deployment, Alias
from sqlalchemy import select, delete
import time
import docker

def cleanup_project(project_id: str, batch_size: int = 100):
    """
    Clean up a deleted project's data in batches.
    
    Args:
        project_id: The ID of the project to clean up
        batch_size: Number of deployments to process in each batch
    """
    # Initialize fresh app and docker client for this task
    app = create_app()
    docker_client = docker.from_env()

    with app.app_context():
        try:
            project = db.session.get(Project, project_id)
            if not project:
                app.logger.warning(f"Cleanup task: Project {project_id} not found")
                return
            if project.status != 'deleted':
                app.logger.warning(f"Cleanup task: Project {project_id} is not marked as deleted")
                return

            app.logger.info(f"Starting cleanup for project {project.name} ({project_id})")
            start_time = time.time()
            total_deployments = 0
            total_aliases = 0
            total_containers = 0

            while True:
                # Get a batch of deployments
                deployments = db.session.scalars(
                    select(Deployment)
                    .where(Deployment.project_id == project_id)
                    .limit(batch_size)
                ).all()

                if not deployments:
                    break

                deployment_ids = [d.id for d in deployments]
                
                # Remove containers
                for deployment in deployments:
                    if deployment.container_id:
                        try:
                            docker_client.containers.get(deployment.container_id).remove(force=True)
                            total_containers += 1
                        except docker.errors.NotFound:
                            app.logger.warning(f"Container {deployment.container_id} not found")
                        except Exception as e:
                            app.logger.error(f"Failed to remove container {deployment.container_id}: {str(e)}")

                try:
                    # Delete aliases
                    result = db.session.execute(
                        delete(Alias).where(Alias.deployment_id.in_(deployment_ids))
                    )
                    total_aliases += result.rowcount

                    # Delete deployments
                    result = db.session.execute(
                        delete(Deployment).where(Deployment.id.in_(deployment_ids))
                    )
                    total_deployments += result.rowcount

                    db.session.commit()
                    app.logger.info(f"Processed batch of {len(deployment_ids)} deployments")

                except Exception as e:
                    app.logger.error(f"Failed to commit batch: {str(e)}")
                    db.session.rollback()
                    time.sleep(1)
                    continue

            # No more deployments, delete the project
            try:
                db.session.execute(
                    delete(Project).where(Project.id == project_id)
                )
                db.session.commit()
                
                duration = time.time() - start_time
                app.logger.info(
                    f"Completed cleanup of project {project.name} ({project_id}) in {duration:.2f}s:\n"
                    f"- {total_deployments} deployments removed\n"
                    f"- {total_aliases} aliases removed\n"
                    f"- {total_containers} containers removed"
                )
            except Exception as e:
                app.logger.error(f"Failed to delete project {project_id}: {str(e)}")
                db.session.rollback()
                raise

        except Exception as e:
            app.logger.error(f"Cleanup task failed for project {project_id}: {str(e)}")
            db.session.rollback()
            raise

        finally:
            docker_client.close()