import logging
from db import AsyncSessionLocal
from services.project_monitoring import ProjectMonitoringService

logger = logging.getLogger(__name__)


async def check_inactive_projects(ctx):
    """Tâche périodique pour vérifier les projets inactifs"""
    logger.info("Checking for inactive projects...")
    
    async with AsyncSessionLocal() as db:
        try:
            await ProjectMonitoringService.check_inactive_projects(db)
            await ProjectMonitoringService.check_permanently_disabled_projects(db)
            logger.info("Project monitoring completed successfully")
        except Exception as e:
            logger.error(f"Error in project monitoring: {e}", exc_info=True)
            raise


async def reactivate_project_task(ctx, project_id: str):
    """Tâche pour réactiver un projet"""
    logger.info(f"Reactivating project {project_id}...")
    
    async with AsyncSessionLocal() as db:
        try:
            from models import Project
            from sqlalchemy import select
            
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            
            if project:
                success = await ProjectMonitoringService.reactivate_project(project, db)
                if success:
                    logger.info(f"Project {project_id} reactivated successfully")
                else:
                    logger.warning(f"Project {project_id} cannot be reactivated")
            else:
                logger.error(f"Project {project_id} not found")
        except Exception as e:
            logger.error(f"Error reactivating project {project_id}: {e}", exc_info=True)
            raise
