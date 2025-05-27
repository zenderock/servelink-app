from app import create_app, db
from app.models import Project, Deployment, Alias
from sqlalchemy import select, delete, or_
import time
import docker
import os

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
                app.logger.warning(f"[ProjectCleanup:{project_id}] Project not found")
                return
            if project.status != 'deleted':
                app.logger.warning(f"[ProjectCleanup:{project_id}] Project is not marked as deleted")
                return

            app.logger.info(f"[ProjectCleanup:{project_id}] Starting cleanup for project {project.name}")
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
                            app.logger.warning(f"[ProjectCleanup:{project_id}] Container {deployment.container_id} not found for deployment {deployment.id}")
                        except Exception as e:
                            app.logger.error(f"[ProjectCleanup:{project_id}] Failed to remove container {deployment.container_id} for deployment {deployment.id}: {str(e)}")

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
                    app.logger.info(f"[ProjectCleanup:{project_id}] Processed batch of {len(deployment_ids)} deployments")

                except Exception as e:
                    app.logger.error(f"[ProjectCleanup:{project_id}] Failed to commit batch: {str(e)}")
                    db.session.rollback()
                    time.sleep(1)
                    continue

            # No more deployments:
            # 1. Remove Traefik config file
            project_config_file_path = os.path.join('/traefik_configs', f"project_{project_id}.yml")
            if os.path.exists(project_config_file_path):
                try:
                    os.remove(project_config_file_path)
                    app.logger.info(f"[ProjectCleanup:{project_id}] Removed Traefik config file {project_config_file_path}")
                except Exception as e_remove:
                    app.logger.error(f"[ProjectCleanup:{project_id}] Failed to remove Traefik config file {project_config_file_path}: {e_remove}", exc_info=True)
                    
            # 2. Delete the project
            try:
                db.session.execute(
                    delete(Project).where(Project.id == project_id)
                )
                db.session.commit()
                
                duration = time.time() - start_time
                app.logger.info(
                    f"[ProjectCleanup:{project_id}] Completed cleanup for project {project.name} in {duration:.2f}s:\\n"
                    f"- {total_deployments} deployments removed\\n"
                    f"- {total_aliases} aliases removed\\n"
                    f"- {total_containers} containers removed"
                )
            except Exception as e:
                app.logger.error(f"[ProjectCleanup:{project_id}] Failed to delete project: {str(e)}")
                db.session.rollback()
                raise

        except Exception as e:
            app.logger.error(f"[ProjectCleanup:{project_id}] Task failed: {str(e)}")
            db.session.rollback()
            raise

        finally:
            docker_client.close()


def cleanup_inactive_deployments(project_id: str, remove_containers: bool = True):
    """
    Stops (and optionally removes) Docker containers for an ACTIVE project whose deployments
    are no longer referenced by any current (Alias.deployment_id) or 
    previous (Alias.previous_deployment_id) alias for that project.
    This task does NOT delete database records for Deployments or Aliases.

    Args:
        project_id: The ID of the project to clean up inactive containers for.
        remove_containers: If True, also remove the containers after stopping. Defaults to True.
    """
    app = create_app()
    docker_client = docker.from_env()

    with app.app_context():
        project = db.session.get(Project, project_id)
        if not project:
            app.logger.warning(f"[InactiveDeploymentsCleanup:{project_id}] Project not found.")
            docker_client.close()
            return
        
        if project.status == 'deleted':
            app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] Project is marked deleted. Full cleanup handled by cleanup_project task. Skipping inactive container check.")
            docker_client.close()
            return

        app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] Starting inactive container check for project {project.name}")

        # Get all deployment IDs that are "active" (current or previous in aliases)
        active_deployment_ids = set(db.session.scalars(
            select(Alias.deployment_id)
            .join(Deployment, Alias.deployment_id == Deployment.id)
            .where(Deployment.project_id == project_id, Alias.deployment_id.isnot(None))
            .union(
                select(Alias.previous_deployment_id)
                .join(Deployment, Alias.deployment_id == Deployment.id)
                .where(Deployment.project_id == project_id, Alias.previous_deployment_id.isnot(None))
            )
        ).all())
        
        app.logger.debug(f"[InactiveDeploymentsCleanup:{project_id}] Active deployment IDs: {active_deployment_ids}")

        # Get deployments with containers that are NOT protected
        inactive_deployments = db.session.scalars(
            select(Deployment)
            .where(
                Deployment.project_id == project_id,
                Deployment.container_id.isnot(None),
                Deployment.container_status == 'running',
                Deployment.status == 'completed',
                Deployment.id.notin_(active_deployment_ids) if active_deployment_ids else True
            )
        ).all()

        stopped_count = 0
        removed_count = 0

        for deployment in inactive_deployments:
            app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] Deployment {deployment.id} (container: {deployment.container_id}) appears inactive.")
            try:
                container = docker_client.containers.get(deployment.container_id)
                app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] Stopping container {container.short_id} ({container.name}) for inactive deployment {deployment.id}.")
                container.stop()
                deployment.container_status = 'stopped'
                stopped_count += 1

                if remove_containers:
                    app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] Removing container {container.short_id} ({container.name}) for inactive deployment {deployment.id}.")
                    container.remove()
                    deployment.container_status = 'removed'
                    removed_count += 1

            except docker.errors.NotFound:
                app.logger.warning(f"[InactiveDeploymentsCleanup:{project_id}] Container {deployment.container_id} for inactive deployment {deployment.id} not found by Docker.")
                deployment.container_status = None
            except Exception as e:
                app.logger.error(f"[InactiveDeploymentsCleanup:{project_id}] Error processing container {deployment.container_id} for inactive deployment {deployment.id}: {e}", exc_info=True)
        
        # Commit any container_status updates
        if stopped_count > 0 or removed_count > 0:
            try:
                db.session.commit()
            except Exception as e:
                app.logger.error(f"[InactiveDeploymentsCleanup:{project_id}] Failed to commit container status updates: {e}")
                db.session.rollback()
        
        if stopped_count > 0:
            app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] Finished. Stopped: {stopped_count} containers. Removed: {removed_count} containers.")
        else:
            app.logger.info(f"[InactiveDeploymentsCleanup:{project_id}] No inactive containers found to stop.")
        
        docker_client.close()