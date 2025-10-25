from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import ProjectUsage, Project, Team
import csv
import io
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service d'analytics avancé avec graphiques et exports"""
    
    @staticmethod
    async def get_usage_trends(
        team_id: str,
        months: int,
        db: AsyncSession
    ) -> dict:
        """
        Récupère les tendances d'utilisation sur plusieurs mois
        
        Args:
            team_id: ID de l'équipe
            months: Nombre de mois à récupérer
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les tendances par mois
        """
        now = datetime.now(timezone.utc)
        trends = []
        
        for i in range(months):
            month_date = now - timedelta(days=30 * i)
            month = month_date.month
            year = month_date.year
            
            # Agrégation par équipe pour ce mois
            result = await db.execute(
                select(
                    func.sum(ProjectUsage.traffic_bytes).label('traffic'),
                    func.sum(ProjectUsage.storage_bytes).label('storage')
                )
                .join(Project, ProjectUsage.project_id == Project.id)
                .where(
                    Project.team_id == team_id,
                    ProjectUsage.month == month,
                    ProjectUsage.year == year
                )
            )
            
            row = result.first()
            traffic = row.traffic or 0
            storage = row.storage or 0
            
            trends.append({
                "month": f"{year}-{month:02d}",
                "traffic_gb": round(traffic / (1024**3), 2),
                "storage_mb": round(storage / (1024**2), 2),
                "traffic_bytes": traffic,
                "storage_bytes": storage
            })
        
        # Inverser pour avoir du plus ancien au plus récent
        trends.reverse()
        
        return {
            "trends": trends,
            "period": f"Last {months} months"
        }
    
    @staticmethod
    async def get_project_comparison(
        team_id: str,
        month: int,
        year: int,
        db: AsyncSession
    ) -> dict:
        """
        Compare l'utilisation entre les projets d'une équipe
        
        Args:
            team_id: ID de l'équipe
            month: Mois
            year: Année
            db: Session de base de données
            
        Returns:
            Comparaison par projet
        """
        result = await db.execute(
            select(
                Project.id,
                Project.name,
                ProjectUsage.traffic_bytes,
                ProjectUsage.storage_bytes
            )
            .join(ProjectUsage, Project.id == ProjectUsage.project_id)
            .where(
                Project.team_id == team_id,
                ProjectUsage.month == month,
                ProjectUsage.year == year,
                Project.status == "active"
            )
            .order_by(ProjectUsage.traffic_bytes.desc())
        )
        
        projects = []
        total_traffic = 0
        total_storage = 0
        
        for row in result:
            traffic = row.traffic_bytes or 0
            storage = row.storage_bytes or 0
            
            total_traffic += traffic
            total_storage += storage
            
            projects.append({
                "project_id": row.id,
                "project_name": row.name,
                "traffic_gb": round(traffic / (1024**3), 2),
                "storage_mb": round(storage / (1024**2), 2),
                "traffic_bytes": traffic,
                "storage_bytes": storage
            })
        
        # Calculer les pourcentages
        for project in projects:
            if total_traffic > 0:
                project["traffic_percentage"] = round((project["traffic_bytes"] / total_traffic) * 100, 1)
            else:
                project["traffic_percentage"] = 0
            
            if total_storage > 0:
                project["storage_percentage"] = round((project["storage_bytes"] / total_storage) * 100, 1)
            else:
                project["storage_percentage"] = 0
        
        return {
            "projects": projects,
            "total_traffic_gb": round(total_traffic / (1024**3), 2),
            "total_storage_mb": round(total_storage / (1024**2), 2),
            "period": f"{year}-{month:02d}"
        }
    
    @staticmethod
    async def predict_usage(
        team_id: str,
        db: AsyncSession
    ) -> dict:
        """
        Prédit l'utilisation future basée sur les tendances
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            
        Returns:
            Prédictions pour le mois prochain
        """
        # Récupérer les 3 derniers mois
        trends = await AnalyticsService.get_usage_trends(team_id, 3, db)
        
        if len(trends["trends"]) < 2:
            return {
                "prediction_available": False,
                "message": "Not enough data for prediction"
            }
        
        # Calculer la croissance moyenne
        traffic_values = [t["traffic_gb"] for t in trends["trends"]]
        storage_values = [t["storage_mb"] for t in trends["trends"]]
        
        # Croissance simple (moyenne des différences)
        traffic_growth = 0
        storage_growth = 0
        
        for i in range(1, len(traffic_values)):
            traffic_growth += traffic_values[i] - traffic_values[i-1]
            storage_growth += storage_values[i] - storage_values[i-1]
        
        if len(traffic_values) > 1:
            traffic_growth /= (len(traffic_values) - 1)
            storage_growth /= (len(storage_values) - 1)
        
        # Prédiction pour le mois prochain
        current_traffic = traffic_values[-1] if traffic_values else 0
        current_storage = storage_values[-1] if storage_values else 0
        
        predicted_traffic = max(0, current_traffic + traffic_growth)
        predicted_storage = max(0, current_storage + storage_growth)
        
        return {
            "prediction_available": True,
            "current": {
                "traffic_gb": current_traffic,
                "storage_mb": current_storage
            },
            "predicted": {
                "traffic_gb": round(predicted_traffic, 2),
                "storage_mb": round(predicted_storage, 2)
            },
            "growth": {
                "traffic_gb_per_month": round(traffic_growth, 2),
                "storage_mb_per_month": round(storage_growth, 2)
            }
        }
    
    @staticmethod
    async def export_to_csv(
        team_id: str,
        months: int,
        db: AsyncSession
    ) -> str:
        """
        Exporte les statistiques en CSV
        
        Args:
            team_id: ID de l'équipe
            months: Nombre de mois
            db: Session de base de données
            
        Returns:
            Contenu CSV
        """
        trends = await AnalyticsService.get_usage_trends(team_id, months, db)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Headers
        writer.writerow(['Month', 'Traffic (GB)', 'Storage (MB)'])
        
        # Data
        for trend in trends["trends"]:
            writer.writerow([
                trend["month"],
                trend["traffic_gb"],
                trend["storage_mb"]
            ])
        
        return output.getvalue()
    
    @staticmethod
    async def get_top_consumers(
        team_id: str,
        limit: int,
        db: AsyncSession
    ) -> dict:
        """
        Récupère les projets qui consomment le plus de ressources
        
        Args:
            team_id: ID de l'équipe
            limit: Nombre de projets à retourner
            db: Session de base de données
            
        Returns:
            Top consommateurs
        """
        now = datetime.now(timezone.utc)
        
        result = await db.execute(
            select(
                Project.id,
                Project.name,
                ProjectUsage.traffic_bytes,
                ProjectUsage.storage_bytes
            )
            .join(ProjectUsage, Project.id == ProjectUsage.project_id)
            .where(
                Project.team_id == team_id,
                ProjectUsage.month == now.month,
                ProjectUsage.year == now.year,
                Project.status == "active"
            )
            .order_by(
                (ProjectUsage.traffic_bytes + ProjectUsage.storage_bytes).desc()
            )
            .limit(limit)
        )
        
        top_projects = []
        for row in result:
            top_projects.append({
                "project_id": row.id,
                "project_name": row.name,
                "traffic_gb": round((row.traffic_bytes or 0) / (1024**3), 2),
                "storage_mb": round((row.storage_bytes or 0) / (1024**2), 2),
                "total_usage_score": round(
                    (row.traffic_bytes or 0) / (1024**3) + 
                    (row.storage_bytes or 0) / (1024**2) / 1000,
                    2
                )
            })
        
        return {
            "top_consumers": top_projects,
            "period": f"{now.year}-{now.month:02d}",
            "limit": limit
        }
    
    @staticmethod
    async def get_analytics_summary(
        team_id: str,
        db: AsyncSession
    ) -> dict:
        """
        Récupère un résumé complet des analytics
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            
        Returns:
            Résumé complet
        """
        # Tendances 6 mois
        trends = await AnalyticsService.get_usage_trends(team_id, 6, db)
        
        # Comparaison projets mois en cours
        now = datetime.now(timezone.utc)
        comparison = await AnalyticsService.get_project_comparison(
            team_id, now.month, now.year, db
        )
        
        # Prédictions
        prediction = await AnalyticsService.predict_usage(team_id, db)
        
        # Top consommateurs
        top = await AnalyticsService.get_top_consumers(team_id, 5, db)
        
        return {
            "trends": trends,
            "comparison": comparison,
            "prediction": prediction,
            "top_consumers": top
        }
