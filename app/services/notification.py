import logging
from typing import Optional
from sqlalchemy.orm import joinedload
from sqlalchemy import select

from models import Deployment, User
from services.onesignal import OneSignalService
from dependencies import templates
from config import Settings

logger = logging.getLogger(__name__)


class DeploymentNotificationService:
    """Service for sending deployment notifications via email."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.onesignal_service = OneSignalService(settings)
    
    async def send_deployment_notification(
        self,
        deployment: Deployment,
        user: User,
        reason: Optional[str] = None
    ) -> bool:
        """
        Send deployment notification email to the user who created the deployment.
        
        Args:
            deployment: The deployment object
            user: The user who created the deployment
            reason: Optional reason for failure (only used for failed deployments)
            
        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        try:
            # Get environment name
            environment = deployment.environment
            environment_name = environment.get("name", "Unknown") if environment else "Unknown"
            
            # Determine subject based on conclusion
            if deployment.conclusion == "succeeded":
                subject = f"Deployment Successful - {deployment.project.name}"
            else:
                subject = f"Deployment Failed - {deployment.project.name}"
            
            # Render email template
            html_content = templates.get_template("email/deployment-notification.html").render(
                {
                    "project_name": deployment.project.name,
                    "deployment_id": deployment.id,
                    "conclusion": deployment.conclusion,
                    "deployment_url": deployment.url,
                    "commit_sha": deployment.commit_sha,
                    "branch": deployment.branch,
                    "environment_name": environment_name,
                    "reason": reason,
                    "email_logo": self.settings.email_logo,
                    "app_name": self.settings.app_name,
                    "app_description": self.settings.app_description,
                    "app_url": f"{self.settings.url_scheme}://{self.settings.app_hostname}",
                }
            )
            
            # Send email via OneSignal
            await self.onesignal_service.send_email(
                to_email=user.email,
                subject=subject,
                html_content=html_content,
                from_name=self.settings.email_sender_name,
                from_address=self.settings.email_sender_address
            )
            
            logger.info(f"Deployment notification sent to {user.email} for deployment {deployment.id} ({deployment.conclusion})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send deployment notification to {user.email} for deployment {deployment.id}: {str(e)}")
            return False
    
    async def close(self):
        """Close the OneSignal service."""
        await self.onesignal_service.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
