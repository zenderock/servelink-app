from sqlalchemy import select

from models import Project, Deployment


async def get_latest_projects(db, current_project=None, limit=5):
    if current_project:
        result = await db.execute(
            select(Project)
            .where(
                Project.status != 'deleted',
                Project.id != current_project.id
            )
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
    else:
        result = await db.execute(
            select(Project)
            .where(Project.status != 'deleted')
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
    
    return result.scalars().all()


async def get_latest_deployments(db, project_id, current_deployment=None, limit=5):
    if current_deployment:
        result = await db.execute(
            select(Deployment)
            .where(
                Deployment.project_id == project_id,
                Deployment.id != current_deployment.id
            )
            .order_by(Deployment.created_at.desc())
            .limit(limit)
        )
    else:
        result = await db.execute(
            select(Deployment)
            .where(Deployment.project_id == project_id)
            .order_by(Deployment.created_at.desc())
            .limit(limit)
        )
    
    return result.scalars().all()