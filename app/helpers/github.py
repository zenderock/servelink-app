from flask import current_app
from app.models import GithubInstallation
from app import db
from datetime import datetime, timezone


def get_installation_instance(installation_id: int) -> GithubInstallation:
    """
    Retrieve the GithubInstallation SQLAlchemy instance for a given installation.
    If no record exists, create one.
    If the token is missing or expired, refresh it.
    """
    installation = db.session.get(GithubInstallation, installation_id)
    
    if not installation:
        installation = GithubInstallation(installation_id=installation_id)
    if (
        not installation.token
        or (
            installation.token_expires_at
            and installation.token_expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)
        )
    ):
        token_data = current_app.github.get_installation_access_token(installation_id)
        installation.token = token_data['token']
        installation.token_expires_at = datetime.fromisoformat(
            token_data['expires_at'].replace('Z', '+00:00')
        ).replace(tzinfo=None)

    installation = db.session.merge(installation)
    db.session.commit()
    return installation