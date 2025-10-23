from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from services.project_monitoring import ProjectMonitoringService
from db import AsyncSessionLocal
from config import get_settings
import logging

logger = logging.getLogger(__name__)


class TrafficRecorderMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, deploy_domain: str = None):
        super().__init__(app)
        self.deploy_domain = deploy_domain or get_settings().deploy_domain

    async def dispatch(self, request: Request, call_next):
        # Vérifier si c'est une requête vers un domaine de projet
        host = request.headers.get("host", "")
        
        # Ignorer les requêtes vers l'API ou l'interface admin
        if (request.url.path.startswith("/api/") or 
            request.url.path.startswith("/auth/") or
            request.url.path.startswith("/team/") or
            request.url.path.startswith("/user/") or
            host.endswith((".localhost", ".local"))):
            response = await call_next(request)
            return response
        
        # Vérifier si c'est un domaine de projet (subdomain.deploy_domain)
        if not host.endswith(f".{self.deploy_domain}"):
            response = await call_next(request)
            return response
        
        # Extraire le subdomain
        subdomain = host.replace(f".{self.deploy_domain}", "")
        
        async with AsyncSessionLocal() as db:
            try:
                # Trouver le projet par alias/subdomain
                project = await ProjectMonitoringService.get_project_by_alias(db, subdomain)
                
                if not project:
                    # Essayer de trouver par domaine personnalisé
                    project = await ProjectMonitoringService.get_project_by_domain(db, host)
                
                if project:
                    # Vérifier le statut du projet
                    if project.status in ["inactive", "permanently_disabled"]:
                        # Bloquer l'accès et afficher page d'erreur
                        return self._create_disabled_page(project)
                    
                    # Enregistrer le trafic de manière asynchrone
                    try:
                        await ProjectMonitoringService.record_traffic(project, db)
                    except Exception as e:
                        logger.error(f"Error recording traffic for project {project.id}: {e}")
                
                # Continuer avec la requête normale
                response = await call_next(request)
                return response
                
            except Exception as e:
                logger.error(f"Error in traffic recorder middleware: {e}")
                response = await call_next(request)
                return response

    def _create_disabled_page(self, project) -> HTMLResponse:
        """Crée une page d'erreur pour les projets désactivés"""
        if project.status == "permanently_disabled":
            title = "Project permanently disabled"
            message = "This project has been permanently disabled after a prolonged period of inactivity and cannot be reactivated."
            action_text = "Contact support for more information."
        else:  # inactive
            title = "Project temporarily disabled"
            message = "This project has been temporarily disabled due to inactivity. It can be reactivated from your dashboard."
            action_text = "Sign in to reactivate the project."
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }}
                .container {{
                    background: white;
                    border-radius: 12px;
                    padding: 3rem;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    text-align: center;
                    max-width: 500px;
                    margin: 2rem;
                }}
                .icon {{
                    font-size: 4rem;
                    margin-bottom: 1rem;
                }}
                h1 {{
                    color: #333;
                    margin-bottom: 1rem;
                    font-size: 1.5rem;
                }}
                p {{
                    color: #666;
                    line-height: 1.6;
                    margin-bottom: 2rem;
                }}
                .action {{
                    background: #667eea;
                    color: white;
                    padding: 0.75rem 1.5rem;
                    border: none;
                    border-radius: 6px;
                    text-decoration: none;
                    display: inline-block;
                    font-weight: 500;
                }}
                .action:hover {{
                    background: #5a6fd8;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon">⚠️</div>
                <h1>{title}</h1>
                <p>{message}</p>
                <p><strong>Project:</strong> {project.name}</p>
                <a href="/auth/login" class="action">{action_text}</a>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content, status_code=503)
