from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from db import get_db
from dependencies import templates, TemplateResponse, get_current_user
from models import User, Team, SupportTicket, TeamMember
from services.support import SupportService
from services.support_notifications import SupportNotificationService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["support_pages"])


@router.get("/support", name="support_index", response_class=HTMLResponse)
async def support_index(
    request: Request,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Page de liste des tickets de support"""
    
    # Récupérer tous les tickets de l'utilisateur
    tickets = await SupportService.get_user_tickets(
        current_user.id, 
        db, 
        status_filter=status if status != "all" else None
    )
    
    # Récupérer les teams de l'utilisateur pour le formulaire
    result = await db.execute(
        select(Team)
        .join(TeamMember)
        .where(TeamMember.user_id == current_user.id)
    )
    teams = result.scalars().all()
    
    return templates.TemplateResponse(
        request,
        "support/pages/index.html",
        {
            "tickets": tickets,
            "teams": teams,
            "status": status or "all",
        }
    )


@router.post("/support/create", name="support_create_ticket")
async def create_ticket(
    request: Request,
    team_id: str = Form(...),
    subject: str = Form(...),
    description: str = Form(...),
    category: str = Form("technical"),
    priority: str = Form("normal"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Créer un nouveau ticket de support"""
    
    try:
        # Vérifier que l'utilisateur appartient à la team
        result = await db.execute(
            select(TeamMember)
            .where(TeamMember.user_id == current_user.id)
            .where(TeamMember.team_id == team_id)
        )
        membership = result.scalar_one_or_none()
        
        if not membership:
            raise HTTPException(status_code=403, detail="You are not a member of this team")
        
        # Créer le ticket
        ticket = await SupportService.create_ticket(
            team_id=team_id,
            user_id=current_user.id,
            subject=subject,
            description=description,
            db=db,
            category=category,
            priority=priority
        )
        
        # Flash message success
        request.session["flash_messages"] = [
            {
                "type": "success",
                "message": f"Ticket #{ticket.id[:8]} created successfully"
            }
        ]
        
        return RedirectResponse(
            url=f"/support/tickets/{ticket.id}",
            status_code=303
        )
    
    except Exception as e:
        logger.error(f"Error creating ticket: {e}")
        request.session["flash_messages"] = [
            {
                "type": "error",
                "message": "Failed to create ticket. Please try again."
            }
        ]
        return RedirectResponse(url="/support", status_code=303)


@router.get("/support/tickets/{ticket_id}", name="support_ticket", response_class=HTMLResponse)
async def view_ticket(
    request: Request,
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Page de détail d'un ticket"""
    
    ticket = await SupportService.get_ticket(ticket_id, db, load_messages=True)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Vérifier que l'utilisateur a accès au ticket
    if ticket.user_id != current_user.id:
        # Vérifier s'il est membre de la team
        result = await db.execute(
            select(TeamMember)
            .where(TeamMember.user_id == current_user.id)
            .where(TeamMember.team_id == ticket.team_id)
        )
        membership = result.scalar_one_or_none()
        
        if not membership:
            raise HTTPException(status_code=403, detail="Access denied")
    
    return templates.TemplateResponse(
        request,
        "support/pages/ticket.html",
        {
            "ticket": ticket,
        }
    )


@router.post("/support/tickets/{ticket_id}/message", name="support_add_message")
async def add_message(
    request: Request,
    ticket_id: str,
    message: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ajouter un message à un ticket"""
    
    try:
        # Vérifier que le ticket existe
        ticket = await SupportService.get_ticket(ticket_id, db)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Vérifier l'accès
        if ticket.user_id != current_user.id:
            result = await db.execute(
                select(TeamMember)
                .where(TeamMember.user_id == current_user.id)
                .where(TeamMember.team_id == ticket.team_id)
            )
            if not result.scalar_one_or_none():
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Ajouter le message
        await SupportService.add_message(
            ticket_id=ticket_id,
            user_id=current_user.id,
            message=message,
            db=db,
            author_type="user"
        )
        
        request.session["flash_messages"] = [
            {
                "type": "success",
                "message": "Message sent successfully"
            }
        ]
        
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        request.session["flash_messages"] = [
            {
                "type": "error",
                "message": "Failed to send message"
            }
        ]
    
    return RedirectResponse(
        url=f"/support/tickets/{ticket_id}",
        status_code=303
    )


@router.post("/support/tickets/{ticket_id}/close", name="support_close_ticket")
async def close_ticket(
    request: Request,
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fermer un ticket"""
    
    try:
        ticket = await SupportService.get_ticket(ticket_id, db)
        if not ticket or ticket.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        await SupportService.update_ticket_status(
            ticket_id, "closed", db
        )
        
        request.session["flash_messages"] = [
            {
                "type": "success",
                "message": "Ticket closed successfully"
            }
        ]
        
    except Exception as e:
        logger.error(f"Error closing ticket: {e}")
        request.session["flash_messages"] = [
            {
                "type": "error",
                "message": "Failed to close ticket"
            }
        ]
    
    return RedirectResponse(
        url=f"/support/tickets/{ticket_id}",
        status_code=303
    )


@router.post("/support/tickets/{ticket_id}/reopen", name="support_reopen_ticket")
async def reopen_ticket(
    request: Request,
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marquer un ticket comme résolu"""
    
    try:
        ticket = await SupportService.get_ticket(ticket_id, db)
        if not ticket or ticket.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        await SupportService.update_ticket_status(
            ticket_id, "resolved", db
        )
        
        request.session["flash_messages"] = [
            {
                "type": "success",
                "message": "Ticket marked as resolved"
            }
        ]
        
    except Exception as e:
        logger.error(f"Error updating ticket: {e}")
        request.session["flash_messages"] = [
            {
                "type": "error",
                "message": "Failed to update ticket"
            }
        ]
    
    return RedirectResponse(
        url=f"/support/tickets/{ticket_id}",
        status_code=303
    )
