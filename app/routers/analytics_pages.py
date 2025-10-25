from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from typing import Optional
from db import get_db
from dependencies import templates, TemplateResponse, get_team_by_slug
from models import User, Team, TeamMember
from services.analytics import AnalyticsService
import logging
import io

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics_pages"])


@router.get("/{team_slug}/analytics", name="team_analytics", response_class=HTMLResponse)
async def analytics_index(
    request: Request,
    team_slug: str,
    period: Optional[int] = 30,
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Page analytics du team"""
    
    team, membership = team_and_membership
    
    # Récupérer le résumé complet
    now = datetime.utcnow()
    
    # Trends pour le graphique
    trends_data = await AnalyticsService.get_usage_trends(team.id, 30, db)
    trends = trends_data.get('trends', [])
    
    # Préparer les données pour Chart.js (derniers 30 jours)
    daily_labels = [t['month'] for t in trends[-30:]]
    daily_traffic = [t['traffic_gb'] * 1024 for t in trends[-30:]]  # Convert to MB
    
    # Stats du mois en cours
    current_month_data = await AnalyticsService.get_project_comparison(
        team.id,
        now.month,
        now.year,
        db
    )
    
    # Top consommateurs (pour storage by project)
    top_consumers = await AnalyticsService.get_top_consumers(team.id, 5, db)
    project_stats = top_consumers.get('top_consumers', [])
    
    # Historique mensuel
    monthly_trends = await AnalyticsService.get_usage_trends(team.id, 6, db)
    monthly_data = monthly_trends.get('trends', [])
    
    # Formater les noms de mois
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    for month in monthly_data:
        parts = month['month'].split('-')
        year = int(parts[0])
        month_num = int(parts[1])
        month['month_name'] = f"{month_names[month_num - 1]} {year}"
        month['project_count'] = len(project_stats)
    
    # Calculer les stats pour les cards
    total_traffic_gb = current_month_data.get('total_traffic_gb', 0)
    total_storage_mb = current_month_data.get('total_storage_mb', 0)
    active_projects = len(project_stats)
    
    # Moyenne journalière (approximation)
    avg_daily_traffic_mb = (total_traffic_gb * 1024) / 30 if total_traffic_gb > 0 else 0
    
    # Stats summary
    stats = {
        'total_traffic_gb': total_traffic_gb,
        'total_storage_mb': total_storage_mb,
        'active_projects': active_projects,
        'avg_daily_traffic_mb': avg_daily_traffic_mb,
        'traffic_change': 0,  # TODO: calculer basé sur mois précédent
        'storage_change': 0   # TODO: calculer basé sur mois précédent
    }
    
    # Formatter project_stats pour le template
    for proj in project_stats:
        proj['name'] = proj.get('project_name', 'Unknown')
        proj['storage_mb'] = proj.get('storage_mb', 0)
    
    return templates.TemplateResponse(
        request,
        "analytics/pages/index.html",
        {
            "team": team,
            "role": membership.role,
            "stats": stats,
            "daily_labels": daily_labels,
            "daily_traffic": daily_traffic,
            "project_stats": project_stats,
            "monthly_data": monthly_data,
            "period": period,
        }
    )


@router.get("/{team_slug}/analytics/export", name="team_analytics_export")
async def export_analytics_csv(
    request: Request,
    team_slug: str,
    period: Optional[int] = 30,
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Exporter les analytics en CSV"""
    
    team, membership = team_and_membership
    
    # Générer le CSV avec les méthodes disponibles
    months = max(1, period // 30)  # Convertir jours en mois
    csv_content = await AnalyticsService.export_to_csv(
        team.id,
        months,
        db
    )
    
    # Créer un buffer
    buffer = io.StringIO()
    buffer.write(csv_content)
    buffer.seek(0)
    
    # Nom du fichier
    now = datetime.utcnow()
    filename = f"analytics_{team.slug}_{now.strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )
