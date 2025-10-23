from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from models import Project, Team, TeamSubscription, Domain, User
from services.pricing import PricingService
from services.notification import DeploymentNotificationService
from config import get_settings
import logging

logger = logging.getLogger(__name__)


class ProjectMonitoringService:
    @staticmethod
    async def check_inactive_projects(db: AsyncSession) -> None:
        """Vérifie et désactive les projets inactifs selon les règles de pricing"""
        now = datetime.now(timezone.utc)
        five_days_ago = now - timedelta(days=5)
        
        # Récupérer le plan gratuit
        free_plan = await PricingService.get_default_free_plan(db)
        
        # Récupérer les projets du plan gratuit inactifs depuis 5 jours
        result = await db.execute(
            select(Project)
            .join(Team, Project.team_id == Team.id)
            .join(TeamSubscription, Team.id == TeamSubscription.team_id)
            .where(
                Project.status == "active",
                TeamSubscription.plan_id == free_plan.id,
                Project.last_traffic_at < five_days_ago
            )
        )
        inactive_projects = result.scalars().all()
        
        for project in inactive_projects:
            await ProjectMonitoringService._deactivate_project(project, db, "inactive")
            logger.info(f"Project {project.id} ({project.name}) deactivated due to inactivity")
            
            # Send notification email
            await ProjectMonitoringService._send_disabled_notification(project, db)
    
    @staticmethod
    async def check_permanently_disabled_projects(db: AsyncSession) -> None:
        """Désactive définitivement les projets inactifs depuis 7 jours supplémentaires"""
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        
        # Projets inactifs depuis 7 jours supplémentaires
        result = await db.execute(
            select(Project).where(
                Project.status == "inactive",
                Project.deactivated_at < seven_days_ago
            )
        )
        permanently_disabled_projects = result.scalars().all()
        
        for project in permanently_disabled_projects:
            await ProjectMonitoringService._deactivate_project(project, db, "permanently_disabled")
            logger.info(f"Project {project.id} ({project.name}) permanently disabled")
            
            # Send notification email
            await ProjectMonitoringService._send_permanently_disabled_notification(project, db)
    
    @staticmethod
    async def _deactivate_project(project: Project, db: AsyncSession, new_status: str) -> None:
        """Désactive un projet et met à jour les domaines"""
        project.status = new_status
        project.deactivated_at = datetime.now(timezone.utc)
        
        # Désactiver tous les domaines du projet
        await db.execute(
            update(Domain)
            .where(Domain.project_id == project.id)
            .values(status="disabled")
        )
        
        await db.commit()
        logger.info(f"Project {project.id} ({project.name}) deactivated to {new_status}")
    
    @staticmethod
    async def reactivate_project(project: Project, db: AsyncSession) -> bool:
        """Réactive un projet si possible"""
        if project.status == "permanently_disabled":
            logger.warning(f"Project {project.id} ({project.name}) cannot be reactivated - permanently disabled")
            return False
        
        if project.status == "inactive":
            project.status = "active"
            project.deactivated_at = None
            project.reactivation_count += 1
            
            # Réactiver les domaines
            await db.execute(
                update(Domain)
                .where(Domain.project_id == project.id)
                .values(status="active")
            )
            
            await db.commit()
            logger.info(f"Project {project.id} ({project.name}) reactivated")
            return True
        
        logger.info(f"Project {project.id} ({project.name}) is already active")
        return False
    
    @staticmethod
    async def record_traffic(project: Project, db: AsyncSession) -> None:
        """Enregistre le trafic sur un projet"""
        project.last_traffic_at = datetime.now(timezone.utc)
        await db.commit()
        logger.debug(f"Traffic recorded for project {project.id} ({project.name})")
    
    @staticmethod
    async def get_project_by_domain(db: AsyncSession, hostname: str) -> Project | None:
        """Récupère un projet par son domaine"""
        result = await db.execute(
            select(Project)
            .join(Domain, Project.id == Domain.project_id)
            .where(
                Domain.hostname == hostname,
                Domain.status == "active"
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_project_by_alias(db: AsyncSession, subdomain: str) -> Project | None:
        """Récupère un projet par son alias/subdomain"""
        from models import Alias, Deployment
        
        result = await db.execute(
            select(Project)
            .join(Deployment, Project.id == Deployment.project_id)
            .join(Alias, Deployment.id == Alias.deployment_id)
            .where(
                Alias.subdomain == subdomain,
                Deployment.conclusion == "succeeded"
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def _send_disabled_notification(project: Project, db: AsyncSession) -> None:
        """Send notification email when project is disabled"""
        try:
            # Get project owner and team
            result = await db.execute(
                select(User, Team)
                .join(Team, Project.team_id == Team.id)
                .join(User, Team.created_by_user_id == User.id)
                .where(Project.id == project.id)
            )
            user_team = result.first()
            
            if user_team:
                user, team = user_team
                settings = get_settings()
                
                async with DeploymentNotificationService(settings) as notification_service:
                    await notification_service.send_project_disabled_notification(project, user, team)
                    
        except Exception as e:
            logger.error(f"Failed to send disabled notification for project {project.id}: {e}")
    
    @staticmethod
    async def _send_permanently_disabled_notification(project: Project, db: AsyncSession) -> None:
        """Send notification email when project is permanently disabled"""
        try:
            # Get project owner and team
            result = await db.execute(
                select(User, Team)
                .join(Team, Project.team_id == Team.id)
                .join(User, Team.created_by_user_id == User.id)
                .where(Project.id == project.id)
            )
            user_team = result.first()
            
            if user_team:
                user, team = user_team
                settings = get_settings()
                
                async with DeploymentNotificationService(settings) as notification_service:
                    await notification_service.send_project_permanently_disabled_notification(project, user, team)
                    
        except Exception as e:
            logger.error(f"Failed to send permanently disabled notification for project {project.id}: {e}")
