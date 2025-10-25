from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from models import SupportTicket, User, Team
from config import get_settings
from services.onesignal import OneSignalService
from dependencies import templates
import logging
import httpx

logger = logging.getLogger(__name__)


class SupportNotificationService:
    """Service de notifications email pour le support"""
    
    @staticmethod
    async def send_ticket_created_notification(
        ticket: SupportTicket,
        db: AsyncSession
    ) -> bool:
        """
        Envoie une notification quand un ticket est créé
        
        Args:
            ticket: Le ticket créé
            db: Session de base de données
            
        Returns:
            True si envoyé avec succès
        """
        try:
            user = await db.get(User, ticket.user_id)
            team = await db.get(Team, ticket.team_id)
            
            if not user or not team:
                logger.warning(f"User or team not found for ticket {ticket.id}")
                return False
            
            settings = get_settings()
            
            # TODO: Utiliser le service d'email existant
            # Pour l'instant, on log seulement
            logger.info(
                f"Email notification: Ticket {ticket.id} created by {user.email} "
                f"for team {team.name} - Priority: {ticket.priority}"
            )
            
            # Envoyer email à l'utilisateur
            await SupportNotificationService._send_email(
                to=user.email,
                subject=f"Ticket #{ticket.id[:8]} créé: {ticket.subject}",
                template="ticket_created",
                context={
                    "ticket_id": ticket.id,
                    "subject": ticket.subject,
                    "priority": ticket.priority,
                    "category": ticket.category,
                    "team_name": team.name
                }
            )
            
            # Si priorité haute/urgente, notifier l'équipe support
            if ticket.priority in ["high", "urgent"]:
                await SupportNotificationService._notify_support_team(ticket, user, team)
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending ticket created notification: {e}")
            return False
    
    @staticmethod
    async def send_ticket_updated_notification(
        ticket: SupportTicket,
        old_status: str,
        new_status: str,
        db: AsyncSession
    ) -> bool:
        """
        Envoie une notification quand le statut d'un ticket change
        
        Args:
            ticket: Le ticket
            old_status: Ancien statut
            new_status: Nouveau statut
            db: Session de base de données
            
        Returns:
            True si envoyé avec succès
        """
        try:
            user = await db.get(User, ticket.user_id)
            if not user:
                return False
            
            # Ne notifier que pour certains changements importants
            important_changes = {
                "in_progress": "Votre ticket est en cours de traitement",
                "resolved": "Votre ticket a été résolu",
                "closed": "Votre ticket a été fermé"
            }
            
            if new_status in important_changes:
                logger.info(
                    f"Email notification: Ticket {ticket.id} status changed "
                    f"from {old_status} to {new_status} for {user.email}"
                )
                
                await SupportNotificationService._send_email(
                    to=user.email,
                    subject=f"Ticket #{ticket.id[:8]} - {important_changes[new_status]}",
                    template="ticket_status_changed",
                    context={
                        "ticket_id": ticket.id,
                        "subject": ticket.subject,
                        "old_status": old_status,
                        "new_status": new_status,
                        "message": important_changes[new_status]
                    }
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending ticket updated notification: {e}")
            return False
    
    @staticmethod
    async def send_new_message_notification(
        ticket: SupportTicket,
        message_author_type: str,
        message_content: str,
        db: AsyncSession
    ) -> bool:
        """
        Envoie une notification quand un nouveau message est ajouté
        
        Args:
            ticket: Le ticket
            message_author_type: Type d'auteur (user, support, system)
            message_content: Contenu du message
            db: Session de base de données
            
        Returns:
            True si envoyé avec succès
        """
        try:
            user = await db.get(User, ticket.user_id)
            if not user:
                return False
            
            # Notifier l'utilisateur si c'est une réponse du support
            if message_author_type == "support":
                logger.info(
                    f"Email notification: New support message on ticket {ticket.id} "
                    f"for {user.email}"
                )
                
                await SupportNotificationService._send_email(
                    to=user.email,
                    subject=f"Nouvelle réponse sur votre ticket #{ticket.id[:8]}",
                    template="ticket_new_message",
                    context={
                        "ticket_id": ticket.id,
                        "subject": ticket.subject,
                        "message_preview": message_content[:200]
                    }
                )
            
            # Notifier le support si c'est un message de l'utilisateur
            elif message_author_type == "user":
                team = await db.get(Team, ticket.team_id)
                await SupportNotificationService._notify_support_team(
                    ticket, user, team, f"New user message: {message_content[:100]}"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending new message notification: {e}")
            return False
    
    @staticmethod
    async def send_sla_warning(
        ticket: SupportTicket,
        hours_remaining: int,
        db: AsyncSession
    ) -> bool:
        """
        Envoie une alerte SLA (temps de réponse)
        
        Args:
            ticket: Le ticket
            hours_remaining: Heures restantes avant violation SLA
            db: Session de base de données
            
        Returns:
            True si envoyé avec succès
        """
        try:
            logger.warning(
                f"SLA Warning: Ticket {ticket.id} has {hours_remaining}h remaining"
            )
            
            # Notifier l'équipe support
            await SupportNotificationService._notify_support_team(
                ticket,
                None,
                None,
                f"SLA WARNING: {hours_remaining}h remaining"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending SLA warning: {e}")
            return False
    
    @staticmethod
    async def _send_email(
        to: str,
        subject: str,
        template: str,
        context: dict
    ) -> bool:
        """
        Envoie un email via le service d'email OneSignal
        
        Args:
            to: Destinataire
            subject: Sujet
            template: Template à utiliser
            context: Contexte pour le template
            
        Returns:
            True si envoyé avec succès
        """
        try:
            settings = get_settings()
            
            # Créer le contenu HTML de l'email
            html_content = SupportNotificationService._render_email_template(
                template, context
            )
            
            # Envoyer via OneSignal
            async with OneSignalService(settings) as onesignal:
                await onesignal.send_email(
                    to_email=to,
                    subject=subject,
                    html_content=html_content,
                    from_name=settings.email_sender_name,
                    from_address=settings.email_sender_address,
                    auto_register=True
                )
            
            logger.info(f"Email sent to {to}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending email to {to}: {e}")
            return False
    
    @staticmethod
    def _render_email_template(template: str, context: dict) -> str:
        """
        Génère le contenu HTML d'un email à partir d'un template Jinja2
        
        Args:
            template: Nom du template (sans le chemin email/)
            context: Contexte pour le template
            
        Returns:
            HTML de l'email
        """
        settings = get_settings()
        
        # Enrichir le contexte avec les infos standard
        full_context = {
            **context,
            "email_logo": settings.email_logo,
            "app_name": settings.app_name,
            "app_description": settings.app_description,
            "app_url": f"{settings.url_scheme}://{settings.app_hostname}",
        }
        
        try:
            # Utiliser le système de templates Jinja2
            return templates.get_template(f"email/{template}.html").render(full_context)
        except Exception as e:
            logger.error(f"Error rendering template {template}: {e}")
            # Fallback simple si template non trouvé
            return f"""
                <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <p>{context.get('message', 'Notification from support')}</p>
                </body>
                </html>
            """
    
    @staticmethod
    async def _notify_support_team(
        ticket: SupportTicket,
        user: User | None,
        team: Team | None,
        message: str = ""
    ) -> bool:
        """
        Notifie l'équipe support (webhook, email, etc.)
        
        Args:
            ticket: Le ticket
            user: L'utilisateur
            team: L'équipe
            message: Message supplémentaire
            
        Returns:
            True si notifié avec succès
        """
        try:
            settings = get_settings()
            
            # TODO: Configurer webhook ou email support
            support_email = getattr(settings, 'support_notification_email', 'support@servelink.com')
            webhook_url = getattr(settings, 'support_webhook_url', None)
            
            logger.info(
                f"Support notification: Ticket {ticket.id} - "
                f"Priority: {ticket.priority} - {message}"
            )
            
            # Envoyer au webhook si configuré
            if webhook_url:
                async with httpx.AsyncClient() as client:
                    await client.post(webhook_url, json={
                        "ticket_id": ticket.id,
                        "subject": ticket.subject,
                        "priority": ticket.priority,
                        "status": ticket.status,
                        "user_email": user.email if user else None,
                        "team_name": team.name if team else None,
                        "message": message
                    }, timeout=5.0)
            
            return True
            
        except Exception as e:
            logger.error(f"Error notifying support team: {e}")
            return False


class SLAService:
    """Service de gestion des SLA (Service Level Agreement)"""
    
    # Temps de réponse cibles selon la priorité (en heures)
    SLA_TARGETS = {
        "urgent": 2,    # 2 heures
        "high": 4,      # 4 heures
        "normal": 24,   # 24 heures
        "low": 48       # 48 heures
    }
    
    @staticmethod
    def get_sla_deadline(ticket: SupportTicket) -> datetime:
        """
        Calcule la deadline SLA pour un ticket
        
        Args:
            ticket: Le ticket
            
        Returns:
            Date limite de réponse
        """
        target_hours = SLAService.SLA_TARGETS.get(ticket.priority, 24)
        from datetime import timedelta
        return ticket.created_at + timedelta(hours=target_hours)
    
    @staticmethod
    def is_sla_violated(ticket: SupportTicket) -> bool:
        """
        Vérifie si le SLA est violé
        
        Args:
            ticket: Le ticket
            
        Returns:
            True si violé
        """
        deadline = SLAService.get_sla_deadline(ticket)
        now = datetime.now(timezone.utc)
        
        # Violé si deadline dépassée et ticket toujours ouvert
        if ticket.status in ["open", "waiting"] and now > deadline:
            return True
        
        return False
    
    @staticmethod
    def get_hours_remaining(ticket: SupportTicket) -> float:
        """
        Retourne les heures restantes avant violation SLA
        
        Args:
            ticket: Le ticket
            
        Returns:
            Heures restantes (négatif si déjà violé)
        """
        deadline = SLAService.get_sla_deadline(ticket)
        now = datetime.now(timezone.utc)
        
        delta = deadline - now
        return delta.total_seconds() / 3600
    
    @staticmethod
    async def check_sla_compliance(
        team_id: str,
        db: AsyncSession
    ) -> dict:
        """
        Vérifie la conformité SLA pour une équipe
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            
        Returns:
            Statistiques de conformité
        """
        from sqlalchemy import select
        
        # Tous les tickets résolus des 30 derniers jours
        from datetime import timedelta
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        result = await db.execute(
            select(SupportTicket).where(
                SupportTicket.team_id == team_id,
                SupportTicket.resolved_at.isnot(None),
                SupportTicket.created_at >= thirty_days_ago
            )
        )
        
        tickets = result.scalars().all()
        
        total = len(tickets)
        respected = 0
        violated = 0
        
        for ticket in tickets:
            deadline = SLAService.get_sla_deadline(ticket)
            if ticket.resolved_at <= deadline:
                respected += 1
            else:
                violated += 1
        
        compliance_rate = (respected / total * 100) if total > 0 else 0
        
        return {
            "total_tickets": total,
            "sla_respected": respected,
            "sla_violated": violated,
            "compliance_rate": round(compliance_rate, 1),
            "period": "Last 30 days"
        }
