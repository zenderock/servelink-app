from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import logging

from models import Project, Deployment, User
from dependencies import (
    get_current_user,
    flash,
    get_translation as _,
    TemplateResponse
)
from db import get_db
from utils.pagination import paginate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", name="team_index")
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    projects_result = await db.execute(
        select(Project)
        .where(Project.user_id == current_user.id, Project.status != "deleted")
        .order_by(Project.updated_at.desc())
        .limit(6)
    )
    projects = projects_result.scalars().all()

    deployments_result = await db.execute(
        select(Deployment)
        .options(selectinload(Deployment.aliases))
        .join(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Deployment.created_at.desc())
        .limit(10)
    )
    deployments = deployments_result.scalars().all()

    return TemplateResponse(
        request=request,
        name="pages/index.html",
        context={
            "current_user": current_user,
            "projects": projects,
            "deployments": deployments,
        },
    )


@router.api_route("/projects", name="team_projects")
async def projects(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page = int(request.query_params.get("page", 1))
    per_page = 10

    query = (
        select(Project)
        .where(Project.user_id == current_user.id, Project.status != "deleted")
        .order_by(Project.updated_at.desc())
    )

    pagination = await paginate(db, query, page, per_page)
    projects = pagination.items

    return TemplateResponse(
        request=request,
        name="pages/projects.html",
        context={
            "current_user": current_user,
            "projects": projects,
            "pagination": pagination,
        },
    )