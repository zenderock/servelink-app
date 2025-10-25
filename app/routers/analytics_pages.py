from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import Optional
from db import get_db
from dependencies import templates, TemplateResponse, get_team_by_slug
from models import User, Team, TeamMember
from services.analytics import AnalyticsService
import logging
import io

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics_pages"])


@router.get("/{team_slug}/analytics", name="analytics_index", response_class=HTMLResponse)
async def analytics_index(
    request: Request,
    team_slug: str,
    period: Optional[int] = 30,
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Page analytics du team"""
    
    team, membership = team_and_membership
    
    # Calculer les dates
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=period)
    
    # Récupérer les stats
    stats = await AnalyticsService.get_team_analytics(
        team.id,
        db,
        start_date=start_date,
        end_date=end_date
    )
    
    # Récupérer les données quotidiennes pour le graphique
    daily_data = await AnalyticsService.get_daily_usage(
        team.id,
        db,
        start_date=start_date,
        end_date=end_date
    )
    
    # Préparer les données pour Chart.js
    daily_labels = [d['date'].strftime('%d %b') for d in daily_data]
    daily_traffic = [d['traffic_mb'] for d in daily_data]
    
    # Récupérer les stats par projet
    project_stats = await AnalyticsService.get_project_breakdown(
        team.id,
        db
    )
    
    # Récupérer l'historique mensuel
    monthly_data = await AnalyticsService.get_monthly_history(
        team.id,
        db,
        months=6
    )
    
    # Ajouter les noms de mois
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    for month in monthly_data:
        month['month_name'] = f"{month_names[month['month'] - 1]} {month['year']}"
    
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


@router.get("/{team_slug}/analytics/export", name="analytics_export_csv")
async def export_analytics_csv(
    request: Request,
    team_slug: str,
    period: Optional[int] = 30,
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Exporter les analytics en CSV"""
    
    team, membership = team_and_membership
    
    # Calculer les dates
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=period)
    
    # Récupérer les données
    daily_data = await AnalyticsService.get_daily_usage(
        team.id,
        db,
        start_date=start_date,
        end_date=end_date
    )
    
    # Générer le CSV
    csv_content = await AnalyticsService.export_to_csv(
        team.id,
        db,
        start_date=start_date,
        end_date=end_date
    )
    
    # Créer un buffer
    buffer = io.StringIO()
    buffer.write(csv_content)
    buffer.seek(0)
    
    # Nom du fichier
    filename = f"analytics_{team.slug}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )
