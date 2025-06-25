from functools import wraps
from flask import abort
from flask_login import current_user
from sqlalchemy import select
from app.models import Project, Deployment
from app import db


def load_project(func):
    """Decorator checking the projects exist and can be accessed."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        project_name = kwargs.pop('project_name', None)
        if not project_name:
            abort(404, description="Missing project identifier.")

        project = db.session.scalar(
            select(Project).where(
                Project.name == project_name,
                Project.user_id == current_user.id
            ).limit(1)
        )
        if not project:
            abort(404, description="Project not found or you don't have access.")

        kwargs['project'] = project
        return func(*args, **kwargs)
    return wrapper


def load_deployment(func):
    """Decorator checking that the deployment exists and belongs to the project."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        deployment_id = kwargs.pop('deployment_id', None)
        project = kwargs.get('project')
        
        if not deployment_id or not project:
            abort(404, description="Missing deployment or project context.")

        deployment = db.session.query(Deployment).filter_by(
            id=deployment_id,
            project_id=project.id
        ).first()

        if not deployment:
            abort(404, description="Deployment not found or not associated with this project.")

        kwargs['deployment'] = deployment

        return func(*args, **kwargs)
    return wrapper