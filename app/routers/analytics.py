from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_db
from dependencies import get_current_user, get_team_by_slug
from models import User, Team, TeamMember
from services.analytics import AnalyticsService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/{team_slug}/trends")
async def get_usage_trends(
    team_slug: str,
    months: int = 6,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Récupère les tendances d'utilisation sur plusieurs mois"""
    team, _ = team_and_membership
    
    if months < 1 or months > 24:
        raise HTTPException(status_code=400, detail="Months must be between 1 and 24")
    
    return await AnalyticsService.get_usage_trends(team.id, months, db)


@router.get("/{team_slug}/comparison")
async def get_project_comparison(
    team_slug: str,
    month: int | None = None,
    year: int | None = None,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Compare l'utilisation entre projets"""
    team, _ = team_and_membership
    
    from datetime import datetime
    now = datetime.now()
    month = month or now.month
    year = year or now.year
    
    return await AnalyticsService.get_project_comparison(team.id, month, year, db)


@router.get("/{team_slug}/prediction")
async def get_usage_prediction(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Prédit l'utilisation future"""
    team, _ = team_and_membership
    return await AnalyticsService.predict_usage(team.id, db)


@router.get("/{team_slug}/top-consumers")
async def get_top_consumers(
    team_slug: str,
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Récupère les projets qui consomment le plus"""
    team, _ = team_and_membership
    return await AnalyticsService.get_top_consumers(team.id, limit, db)


@router.get("/{team_slug}/summary")
async def get_analytics_summary(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Résumé complet des analytics"""
    team, _ = team_and_membership
    return await AnalyticsService.get_analytics_summary(team.id, db)


@router.get("/{team_slug}/export/csv")
async def export_to_csv(
    team_slug: str,
    months: int = 6,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """Exporte les statistiques en CSV"""
    team, _ = team_and_membership
    
    csv_content = await AnalyticsService.export_to_csv(team.id, months, db)
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=analytics-{team.slug}.csv"
        }
    )
