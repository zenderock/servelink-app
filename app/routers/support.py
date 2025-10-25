from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from db import get_db
from dependencies import get_current_user, get_team_by_slug
from models import User, Team, TeamMember
from services.support import SupportService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=["support"])


class CreateTicketRequest(BaseModel):
    subject: str
    description: str
    category: str = "technical"
    priority: Optional[str] = "normal"


class AddMessageRequest(BaseModel):
    message: str


@router.post("/{team_slug}/tickets")
async def create_ticket(
    team_slug: str,
    request: CreateTicketRequest,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Crée un nouveau ticket de support
    
    **Corps de la requête:**
    ```json
    {
        "subject": "Problème de déploiement",
        "description": "Mon application ne démarre pas...",
        "category": "technical",
        "priority": "high"
    }
    ```
    
    **Catégories:** technical, billing, feature_request, bug_report, other
    **Priorités:** low, normal, high, urgent (Pro plan a automatiquement high)
    
    **Réponse:**
    ```json
    {
        "ticket_id": "ticket_123",
        "status": "open",
        "priority": "high",
        "created_at": "2025-01-25T10:00:00Z"
    }
    ```
    """
    team, _ = team_and_membership
    
    # Valider la catégorie
    valid_categories = ["technical", "billing", "feature_request", "bug_report", "other"]
    if request.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        )
    
    # Valider la priorité
    valid_priorities = ["low", "normal", "high", "urgent"]
    if request.priority and request.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
        )
    
    try:
        ticket = await SupportService.create_ticket(
            team_id=team.id,
            user_id=current_user.id,
            subject=request.subject,
            description=request.description,
            db=db,
            category=request.category,
            priority=request.priority or "normal"
        )
        
        return {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "priority": ticket.priority,
            "category": ticket.category,
            "created_at": ticket.created_at.isoformat()
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to create ticket")


@router.get("/{team_slug}/tickets")
async def list_tickets(
    team_slug: str,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Liste les tickets d'une équipe
    
    **Paramètres:**
    - status: Filtrer par statut (open, in_progress, waiting, resolved, closed)
    
    **Réponse:**
    ```json
    {
        "tickets": [
            {
                "id": "ticket_123",
                "subject": "Problème de déploiement",
                "status": "in_progress",
                "priority": "high",
                "category": "technical",
                "created_at": "2025-01-25T10:00:00Z",
                "updated_at": "2025-01-25T11:00:00Z"
            }
        ]
    }
    ```
    """
    team, _ = team_and_membership
    
    tickets = await SupportService.get_team_tickets(
        team.id, db, status_filter=status
    )
    
    return {
        "tickets": [
            {
                "id": t.id,
                "subject": t.subject,
                "status": t.status,
                "priority": t.priority,
                "category": t.category,
                "assigned_to": t.assigned_to,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
                "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None
            }
            for t in tickets
        ]
    }


@router.get("/{team_slug}/tickets/{ticket_id}")
async def get_ticket(
    team_slug: str,
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Récupère un ticket avec ses messages
    
    **Réponse:**
    ```json
    {
        "id": "ticket_123",
        "subject": "Problème",
        "description": "Description...",
        "status": "in_progress",
        "priority": "high",
        "messages": [
            {
                "id": "msg_1",
                "author_type": "user",
                "message": "Bonjour...",
                "created_at": "2025-01-25T10:00:00Z"
            }
        ]
    }
    ```
    """
    team, _ = team_and_membership
    
    ticket = await SupportService.get_ticket(ticket_id, db, load_messages=True)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Vérifier que le ticket appartient à l'équipe
    if ticket.team_id != team.id:
        raise HTTPException(
            status_code=403,
            detail="This ticket does not belong to your team"
        )
    
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "category": ticket.category,
        "assigned_to": ticket.assigned_to,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
        "messages": [
            {
                "id": m.id,
                "author_type": m.author_type,
                "message": m.message,
                "created_at": m.created_at.isoformat()
            }
            for m in ticket.messages
            if not m.is_internal  # Ne pas afficher les messages internes
        ]
    }


@router.post("/{team_slug}/tickets/{ticket_id}/messages")
async def add_message(
    team_slug: str,
    ticket_id: str,
    request: AddMessageRequest,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute un message à un ticket
    
    **Corps de la requête:**
    ```json
    {
        "message": "Merci pour votre aide..."
    }
    ```
    
    **Réponse:**
    ```json
    {
        "message_id": "msg_123",
        "created_at": "2025-01-25T11:00:00Z"
    }
    ```
    """
    team, _ = team_and_membership
    
    # Vérifier que le ticket existe et appartient à l'équipe
    ticket = await SupportService.get_ticket(ticket_id, db, load_messages=False)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.team_id != team.id:
        raise HTTPException(
            status_code=403,
            detail="This ticket does not belong to your team"
        )
    
    # Vérifier que le ticket n'est pas fermé
    if ticket.status == "closed":
        raise HTTPException(
            status_code=400,
            detail="Cannot add message to a closed ticket"
        )
    
    try:
        message = await SupportService.add_message(
            ticket_id=ticket_id,
            user_id=current_user.id,
            message=request.message,
            db=db,
            author_type="user"
        )
        
        return {
            "message_id": message.id,
            "created_at": message.created_at.isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        raise HTTPException(status_code=500, detail="Failed to add message")


@router.get("/{team_slug}/stats")
async def get_support_stats(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Récupère les statistiques de support de l'équipe
    
    **Réponse:**
    ```json
    {
        "by_status": {
            "open": 5,
            "in_progress": 3,
            "resolved": 10
        },
        "by_priority": {
            "high": 2,
            "urgent": 1
        },
        "total": 18,
        "open": 8,
        "closed": 10,
        "avg_resolution_hours": 24.5
    }
    ```
    """
    team, _ = team_and_membership
    
    stats = await SupportService.get_ticket_stats(team.id, db)
    
    return stats
