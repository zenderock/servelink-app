from sqlalchemy import select
import secrets
import string

from models import Project, Deployment


async def get_latest_projects(db, team, current_project=None, limit=4):
    query = (
        select(Project)
        .where(Project.status != "deleted", Project.team_id == team.id)
        .order_by(Project.updated_at.desc())
    )

    if limit:
        query = query.limit(limit)

    if current_project:
        query = query.where(Project.id != current_project.id)

    result = await db.execute(query)
    return result.scalars().all()


async def get_latest_deployments(db, project, current_deployment=None, limit=4):
    query = (
        select(Deployment)
        .join(Project)
        .where(Deployment.project_id == project.id, Project.status != "deleted")
        .order_by(Deployment.created_at.desc())
    )

    if limit:
        query = query.limit(limit)

    if current_deployment:
        query = query.where(Deployment.id != current_deployment.id)

    result = await db.execute(query)
    return result.scalars().all()


async def generate_unique_project_name(db, team, base_name: str) -> str:
    """
    Generate a unique project name by appending a random code if the base name already exists.
    """
    # First check if the base name is available
    result = await db.execute(
        select(Project).where(
            Project.team_id == team.id,
            Project.name == base_name,
            Project.status != "deleted"
        )
    )
    
    if not result.scalar_one_or_none():
        return base_name
    
    # Generate a random 4-character code
    def generate_code():
        return ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    
    # Try different codes until we find a unique name
    max_attempts = 10
    for _ in range(max_attempts):
        code = generate_code()
        unique_name = f"{base_name}-{code}"
        
        result = await db.execute(
            select(Project).where(
                Project.team_id == team.id,
                Project.name == unique_name,
                Project.status != "deleted"
            )
        )
        
        if not result.scalar_one_or_none():
            return unique_name
    
    # Fallback: use timestamp if we can't find a unique name
    import time
    timestamp = str(int(time.time()))[-4:]
    return f"{base_name}-{timestamp}"
