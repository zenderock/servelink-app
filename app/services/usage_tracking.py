from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import Project, ProjectUsage, Team
import logging

logger = logging.getLogger(__name__)


class UsageTrackingService:
    """Service de tracking de l'utilisation (trafic et stockage) des projets"""
    
    @staticmethod
    async def record_traffic(
        project_id: str,
        bytes_transferred: int,
        db: AsyncSession
    ) -> None:
        """
        Enregistre le trafic réseau d'un projet pour le mois en cours
        
        Args:
            project_id: ID du projet
            bytes_transferred: Nombre d'octets transférés
            db: Session de base de données
        """
        now = datetime.now(timezone.utc)
        current_month = now.month
        current_year = now.year
        
        try:
            # Chercher l'enregistrement d'utilisation pour ce mois
            result = await db.execute(
                select(ProjectUsage).where(
                    ProjectUsage.project_id == project_id,
                    ProjectUsage.month == current_month,
                    ProjectUsage.year == current_year
                )
            )
            usage = result.scalar_one_or_none()
            
            if usage:
                # Mettre à jour l'enregistrement existant
                usage.traffic_bytes += bytes_transferred
                usage.updated_at = now
            else:
                # Créer un nouvel enregistrement
                usage = ProjectUsage(
                    project_id=project_id,
                    month=current_month,
                    year=current_year,
                    traffic_bytes=bytes_transferred,
                    storage_bytes=0
                )
                db.add(usage)
            
            await db.commit()
            logger.debug(f"Recorded {bytes_transferred} bytes of traffic for project {project_id}")
            
        except Exception as e:
            logger.error(f"Error recording traffic for project {project_id}: {e}")
            await db.rollback()
            raise
    
    @staticmethod
    async def update_storage(
        project_id: str,
        storage_bytes: int,
        db: AsyncSession
    ) -> None:
        """
        Met à jour l'espace disque utilisé par un projet pour le mois en cours
        
        Args:
            project_id: ID du projet
            storage_bytes: Espace disque utilisé en octets
            db: Session de base de données
        """
        now = datetime.now(timezone.utc)
        current_month = now.month
        current_year = now.year
        
        try:
            # Chercher l'enregistrement d'utilisation pour ce mois
            result = await db.execute(
                select(ProjectUsage).where(
                    ProjectUsage.project_id == project_id,
                    ProjectUsage.month == current_month,
                    ProjectUsage.year == current_year
                )
            )
            usage = result.scalar_one_or_none()
            
            if usage:
                # Mettre à jour l'enregistrement existant
                usage.storage_bytes = storage_bytes
                usage.updated_at = now
            else:
                # Créer un nouvel enregistrement
                usage = ProjectUsage(
                    project_id=project_id,
                    month=current_month,
                    year=current_year,
                    traffic_bytes=0,
                    storage_bytes=storage_bytes
                )
                db.add(usage)
            
            await db.commit()
            logger.debug(f"Updated storage to {storage_bytes} bytes for project {project_id}")
            
        except Exception as e:
            logger.error(f"Error updating storage for project {project_id}: {e}")
            await db.rollback()
            raise
    
    @staticmethod
    async def get_monthly_usage(
        project_id: str,
        month: int,
        year: int,
        db: AsyncSession
    ) -> dict:
        """
        Récupère les statistiques d'utilisation d'un projet pour un mois donné
        
        Args:
            project_id: ID du projet
            month: Mois (1-12)
            year: Année
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les statistiques d'utilisation
        """
        result = await db.execute(
            select(ProjectUsage).where(
                ProjectUsage.project_id == project_id,
                ProjectUsage.month == month,
                ProjectUsage.year == year
            )
        )
        usage = result.scalar_one_or_none()
        
        if not usage:
            return {
                "traffic_bytes": 0,
                "traffic_mb": 0,
                "traffic_gb": 0,
                "storage_bytes": 0,
                "storage_mb": 0,
                "storage_gb": 0
            }
        
        return {
            "traffic_bytes": usage.traffic_bytes,
            "traffic_mb": round(usage.traffic_bytes / (1024 * 1024), 2),
            "traffic_gb": round(usage.traffic_bytes / (1024 * 1024 * 1024), 2),
            "storage_bytes": usage.storage_bytes,
            "storage_mb": round(usage.storage_bytes / (1024 * 1024), 2),
            "storage_gb": round(usage.storage_bytes / (1024 * 1024 * 1024), 2)
        }
    
    @staticmethod
    async def get_current_month_usage(
        project_id: str,
        db: AsyncSession
    ) -> dict:
        """
        Récupère les statistiques d'utilisation du mois en cours
        
        Args:
            project_id: ID du projet
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les statistiques d'utilisation
        """
        now = datetime.now(timezone.utc)
        return await UsageTrackingService.get_monthly_usage(
            project_id, now.month, now.year, db
        )
    
    @staticmethod
    async def get_team_usage(
        team_id: str,
        month: int,
        year: int,
        db: AsyncSession
    ) -> dict:
        """
        Récupère les statistiques d'utilisation totales d'une équipe pour un mois donné
        
        Args:
            team_id: ID de l'équipe
            month: Mois (1-12)
            year: Année
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les statistiques d'utilisation de tous les projets de l'équipe
        """
        result = await db.execute(
            select(
                func.sum(ProjectUsage.traffic_bytes).label('total_traffic'),
                func.sum(ProjectUsage.storage_bytes).label('total_storage')
            )
            .join(Project, ProjectUsage.project_id == Project.id)
            .where(
                Project.team_id == team_id,
                ProjectUsage.month == month,
                ProjectUsage.year == year
            )
        )
        
        totals = result.first()
        total_traffic = totals.total_traffic or 0
        total_storage = totals.total_storage or 0
        
        return {
            "traffic_bytes": total_traffic,
            "traffic_mb": round(total_traffic / (1024 * 1024), 2),
            "traffic_gb": round(total_traffic / (1024 * 1024 * 1024), 2),
            "storage_bytes": total_storage,
            "storage_mb": round(total_storage / (1024 * 1024), 2),
            "storage_gb": round(total_storage / (1024 * 1024 * 1024), 2)
        }
    
    @staticmethod
    async def check_usage_limits(
        project: Project,
        team: Team,
        db: AsyncSession
    ) -> tuple[bool, str]:
        """
        Vérifie si un projet dépasse les limites d'utilisation de son plan
        
        Args:
            project: Le projet à vérifier
            team: L'équipe du projet
            db: Session de base de données
            
        Returns:
            Tuple (dans_les_limites, message_erreur)
        """
        plan = team.current_plan
        if not plan:
            return False, "No active plan found"
        
        now = datetime.now(timezone.utc)
        usage = await UsageTrackingService.get_monthly_usage(
            project.id, now.month, now.year, db
        )
        
        # Vérifier le trafic
        traffic_gb = usage["traffic_gb"]
        if traffic_gb > plan.max_traffic_gb_per_month:
            return False, f"Monthly traffic limit exceeded: {traffic_gb:.2f}GB / {plan.max_traffic_gb_per_month}GB on {plan.display_name} plan"
        
        # Vérifier le stockage
        storage_mb = usage["storage_mb"]
        if storage_mb > plan.max_storage_mb:
            return False, f"Storage limit exceeded: {storage_mb:.2f}MB / {plan.max_storage_mb}MB on {plan.display_name} plan"
        
        return True, ""
    
    @staticmethod
    async def get_usage_summary(
        team_id: str,
        db: AsyncSession
    ) -> dict:
        """
        Récupère un résumé de l'utilisation d'une équipe avec les limites du plan
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            
        Returns:
            Dictionnaire avec l'utilisation et les limites
        """
        team = await db.get(Team, team_id)
        if not team:
            return {}
        
        plan = team.current_plan
        if not plan:
            return {}
        
        now = datetime.now(timezone.utc)
        usage = await UsageTrackingService.get_team_usage(
            team_id, now.month, now.year, db
        )
        
        return {
            "plan": {
                "name": plan.name,
                "display_name": plan.display_name,
                "max_traffic_gb": plan.max_traffic_gb_per_month,
                "max_storage_mb": plan.max_storage_mb
            },
            "usage": usage,
            "limits": {
                "traffic": {
                    "used_gb": usage["traffic_gb"],
                    "limit_gb": plan.max_traffic_gb_per_month,
                    "percentage": round((usage["traffic_gb"] / plan.max_traffic_gb_per_month) * 100, 2) if plan.max_traffic_gb_per_month > 0 else 0
                },
                "storage": {
                    "used_mb": usage["storage_mb"],
                    "limit_mb": plan.max_storage_mb,
                    "percentage": round((usage["storage_mb"] / plan.max_storage_mb) * 100, 2) if plan.max_storage_mb > 0 else 0
                }
            }
        }
