from flask import current_app
import requests
from app import db
from app.models import Alias, Deployment
from sqlalchemy import select

def sync_aliases():
    """Sync all active aliases to NGINX"""
    try:
        aliases = db.session.scalars(
            select(Alias)
            .join(Alias.deployment)
            .where(Deployment.conclusion == 'succeeded')
        ).all()

        mappings = {
            f"{alias.subdomain}.{current_app.config['BASE_DOMAIN']}": f"runner-{alias.deployment_id[:7]}"
            for alias in aliases
        }

        if mappings:
            response = requests.post(
                'http://openresty/set-alias',
                json=mappings,
                timeout=5
            )
            response.raise_for_status()
            current_app.logger.info(f"Synced {len(mappings)} aliases to NGINX")
            
    except Exception as e:
        current_app.logger.error(f"Failed to sync aliases to NGINX: {e}") 