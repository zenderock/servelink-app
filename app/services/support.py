from datetime import datetime, timezone
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from models import SupportTicket, SupportMessage, Team, User
import logging

logger = logging.getLogger(__name__)


class SupportService:
    """Service de gestion du support prioritaire"""
    
    @staticmethod
    async def create_ticket(
        team_id: str,
        user_id: int,
        subject: str,
        description: str,
        db: AsyncSession,
        category: str = "technical",
        priority: str = "normal"
    ) -> SupportTicket:
        """
        Crée un nouveau ticket de support
        
        Args:
            team_id: ID de l'équipe
            user_id: ID de l'utilisateur
            subject: Sujet du ticket
            description: Description du problème
            category: Catégorie (technical, billing, feature_request, bug_report, other)
            priority: Priorité (low, normal, high, urgent)
            db: Session de base de données
            
        Returns:
            Le ticket créé
        """
        # Vérifier que l'équipe existe
        team = await db.get(Team, team_id)
        if not team:
            raise ValueError("Team not found")
        
        # Ajuster la priorité selon le plan
        # Plans Pro (pay_as_you_go) ont automatiquement la priorité "high"
        # Plans Free restent en "normal" ou "low"
        if team.current_plan and team.current_plan.name == "pay_as_you_go":
            if priority in ["low", "normal"]:
                priority = "high"
        else:
            # Plan Free : limiter à normal ou low
            if priority in ["high", "urgent"]:
                priority = "normal"
        
        ticket = SupportTicket(
            team_id=team_id,
            user_id=user_id,
            subject=subject,
            description=description,
            category=category,
            priority=priority,
            status="open"
        )
        
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)
        
        # Créer le premier message (description)
        await SupportService.add_message(
            ticket_id=ticket.id,
            user_id=user_id,
            message=description,
            db=db,
            author_type="user"
        )
        
        logger.info(f"Created support ticket {ticket.id} for team {team_id} (priority: {priority})")
        return ticket
    
    @staticmethod
    async def add_message(
        ticket_id: str,
        user_id: int | None,
        message: str,
        db: AsyncSession,
        author_type: str = "user",
        is_internal: bool = False
    ) -> SupportMessage:
        """
        Ajoute un message à un ticket
        
        Args:
            ticket_id: ID du ticket
            user_id: ID de l'utilisateur (None pour les messages système)
            message: Contenu du message
            author_type: Type d'auteur (user, support, system)
            is_internal: Message interne (visible uniquement par le support)
            db: Session de base de données
            
        Returns:
            Le message créé
        """
        ticket = await db.get(SupportTicket, ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        msg = SupportMessage(
            ticket_id=ticket_id,
            user_id=user_id,
            author_type=author_type,
            message=message,
            is_internal=is_internal
        )
        
        db.add(msg)
        
        # Mettre à jour le statut du ticket si c'est une réponse du support
        if author_type == "support" and ticket.status == "waiting":
            ticket.status = "in_progress"
        elif author_type == "user" and ticket.status == "in_progress":
            ticket.status = "waiting"  # En attente de réponse du support
        
        ticket.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(msg)
        
        logger.info(f"Added message to ticket {ticket_id} by {author_type}")
        return msg
    
    @staticmethod
    async def get_ticket(
        ticket_id: str,
        db: AsyncSession,
        load_messages: bool = True
    ) -> SupportTicket | None:
        """
        Récupère un ticket par son ID
        
        Args:
            ticket_id: ID du ticket
            db: Session de base de données
            load_messages: Charger les messages du ticket
            
        Returns:
            Le ticket ou None
        """
        query = select(SupportTicket).where(SupportTicket.id == ticket_id)
        
        if load_messages:
            query = query.options(selectinload(SupportTicket.messages))
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_tickets(
        user_id: int,
        db: AsyncSession,
        status_filter: str | None = None,
        load_messages: bool = False
    ) -> list[SupportTicket]:
        """
        Récupère tous les tickets d'un utilisateur (tous teams confondus)
        
        Args:
            user_id: ID de l'utilisateur
            db: Session de base de données
            status_filter: Filtrer par statut (optionnel)
            load_messages: Charger les messages (par défaut False)
            
        Returns:
            Liste des tickets
        """
        query = select(SupportTicket).where(
            SupportTicket.user_id == user_id
        )
        
        if status_filter:
            query = query.where(SupportTicket.status == status_filter)
        
        if load_messages:
            query = query.options(selectinload(SupportTicket.messages))
        
        query = query.options(
            selectinload(SupportTicket.team),
            selectinload(SupportTicket.user)
        ).order_by(SupportTicket.created_at.desc())
        
        result = await db.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_team_tickets(
        team_id: str,
        db: AsyncSession,
        status_filter: str | None = None,
        limit: int = 50
    ) -> list[SupportTicket]:
        """
        Récupère les tickets d'une équipe
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            status_filter: Filtrer par statut (optionnel)
            limit: Nombre maximum de tickets
            
        Returns:
            Liste des tickets
        """
        query = select(SupportTicket).where(SupportTicket.team_id == team_id)
        
        if status_filter:
            query = query.where(SupportTicket.status == status_filter)
        
        query = query.order_by(SupportTicket.created_at.desc()).limit(limit)
        
        result = await db.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def update_ticket_status(
        ticket_id: str,
        status: str,
        db: AsyncSession,
        assigned_to: str | None = None
    ) -> SupportTicket:
        """
        Met à jour le statut d'un ticket
        
        Args:
            ticket_id: ID du ticket
            status: Nouveau statut
            db: Session de base de données
            assigned_to: Assigné à (optionnel)
            
        Returns:
            Le ticket mis à jour
        """
        ticket = await db.get(SupportTicket, ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        old_status = ticket.status
        ticket.status = status
        ticket.updated_at = datetime.now(timezone.utc)
        
        if assigned_to is not None:
            ticket.assigned_to = assigned_to
        
        # Marquer comme résolu
        if status == "resolved" and old_status != "resolved":
            ticket.resolved_at = datetime.now(timezone.utc)
        
        # Marquer comme fermé
        if status == "closed" and old_status != "closed":
            ticket.closed_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(ticket)
        
        logger.info(f"Updated ticket {ticket_id} status to {status}")
        return ticket
    
    @staticmethod
    async def get_priority_tickets(
        db: AsyncSession,
        limit: int = 100
    ) -> list[SupportTicket]:
        """
        Récupère les tickets prioritaires (high, urgent) non résolus
        
        Args:
            db: Session de base de données
            limit: Nombre maximum de tickets
            
        Returns:
            Liste des tickets prioritaires
        """
        result = await db.execute(
            select(SupportTicket)
            .where(
                SupportTicket.priority.in_(["high", "urgent"]),
                SupportTicket.status.in_(["open", "in_progress", "waiting"])
            )
            .order_by(
                SupportTicket.priority.desc(),
                SupportTicket.created_at.asc()
            )
            .limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def search_tickets(
        query_text: str,
        team_id: str | None,
        db: AsyncSession,
        limit: int = 50
    ) -> list[SupportTicket]:
        """
        Recherche des tickets par mots-clés
        
        Args:
            query_text: Texte de recherche
            team_id: Filtrer par équipe (optionnel)
            db: Session de base de données
            limit: Nombre maximum de résultats
            
        Returns:
            Liste des tickets correspondants
        """
        search = f"%{query_text}%"
        
        query = select(SupportTicket).where(
            or_(
                SupportTicket.subject.ilike(search),
                SupportTicket.description.ilike(search)
            )
        )
        
        if team_id:
            query = query.where(SupportTicket.team_id == team_id)
        
        query = query.order_by(SupportTicket.created_at.desc()).limit(limit)
        
        result = await db.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_ticket_stats(team_id: str, db: AsyncSession) -> dict:
        """
        Récupère les statistiques des tickets d'une équipe
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les statistiques
        """
        from sqlalchemy import func
        
        # Compter par statut
        result = await db.execute(
            select(
                SupportTicket.status,
                func.count(SupportTicket.id).label('count')
            )
            .where(SupportTicket.team_id == team_id)
            .group_by(SupportTicket.status)
        )
        
        status_counts = {row.status: row.count for row in result}
        
        # Compter par priorité
        result = await db.execute(
            select(
                SupportTicket.priority,
                func.count(SupportTicket.id).label('count')
            )
            .where(
                SupportTicket.team_id == team_id,
                SupportTicket.status.in_(["open", "in_progress", "waiting"])
            )
            .group_by(SupportTicket.priority)
        )
        
        priority_counts = {row.priority: row.count for row in result}
        
        # Temps de résolution moyen
        result = await db.execute(
            select(
                func.avg(
                    func.extract('epoch', SupportTicket.resolved_at) - 
                    func.extract('epoch', SupportTicket.created_at)
                ).label('avg_resolution_time')
            )
            .where(
                SupportTicket.team_id == team_id,
                SupportTicket.resolved_at.isnot(None)
            )
        )
        
        avg_time = result.scalar() or 0
        
        return {
            "by_status": status_counts,
            "by_priority": priority_counts,
            "total": sum(status_counts.values()),
            "open": status_counts.get("open", 0) + status_counts.get("in_progress", 0) + status_counts.get("waiting", 0),
            "closed": status_counts.get("resolved", 0) + status_counts.get("closed", 0),
            "avg_resolution_hours": round(avg_time / 3600, 2) if avg_time else 0
        }
