from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from db import get_db
from dependencies import get_current_user, get_team_by_slug
from models import User, Team, TeamMember
from services.payment import PaymentService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


class InitiatePaymentRequest(BaseModel):
    amount: float
    payment_method: str
    plan_upgrade: Optional[bool] = False
    new_plan: Optional[str] = None
    description: Optional[str] = None


class PaymentCallbackRequest(BaseModel):
    external_payment_id: str
    status: str
    metadata: Optional[dict] = {}


@router.post("/{team_slug}/initiate")
async def initiate_payment(
    team_slug: str,
    request: InitiatePaymentRequest,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Initialise un paiement pour une équipe
    
    **Corps de la requête:**
    - amount: Montant du paiement en EUR
    - payment_method: "mobile_money" ou "credit_card"
    - plan_upgrade: true si c'est un upgrade de plan
    - new_plan: Nom du nouveau plan (si plan_upgrade=true)
    - description: Description du paiement
    
    **Réponse:**
    ```json
    {
        "payment_id": "abc123",
        "external_payment_id": "ext_xyz789",
        "status": "pending",
        "amount": 3.0,
        "currency": "EUR",
        "payment_url": "https://payment.example.com/pay/xyz789",
        "qr_code": "data:image/png;base64,..."
    }
    ```
    """
    team, membership = team_and_membership
    
    # Vérifier que l'utilisateur est owner ou admin
    if membership.role not in ["owner", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only team owners and admins can initiate payments"
        )
    
    # Valider la méthode de paiement
    if request.payment_method not in ["mobile_money", "credit_card"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid payment method. Must be 'mobile_money' or 'credit_card'"
        )
    
    # Préparer les métadonnées
    metadata = {
        "description": request.description or "Payment",
        "team_id": team.id,
        "team_name": team.name,
        "user_id": current_user.id,
        "user_email": current_user.email
    }
    
    if request.plan_upgrade:
        metadata["plan_upgrade"] = True
        metadata["new_plan"] = request.new_plan
    
    try:
        payment_service = PaymentService()
        payment = await payment_service.initiate_payment(
            team_id=team.id,
            amount=request.amount,
            payment_method=request.payment_method,
            metadata=metadata,
            db=db
        )
        
        return {
            "payment_id": payment.id,
            "external_payment_id": payment.external_payment_id,
            "status": payment.status,
            "amount": payment.amount,
            "currency": payment.currency,
            "payment_url": payment.metadata.get("payment_url"),
            "qr_code": payment.metadata.get("qr_code"),
            "created_at": payment.created_at.isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error initiating payment: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate payment")


@router.get("/{team_slug}/history")
async def get_payment_history(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Récupère l'historique des paiements d'une équipe
    
    **Réponse:**
    ```json
    {
        "payments": [
            {
                "payment_id": "abc123",
                "amount": 3.0,
                "currency": "EUR",
                "payment_method": "mobile_money",
                "status": "completed",
                "created_at": "2025-01-25T10:00:00Z",
                "completed_at": "2025-01-25T10:05:00Z"
            }
        ]
    }
    ```
    """
    team, _ = team_and_membership
    
    try:
        payment_service = PaymentService()
        payments = await payment_service.get_payment_history(team.id, db, limit=50)
        
        return {
            "payments": [
                {
                    "payment_id": p.id,
                    "amount": p.amount,
                    "currency": p.currency,
                    "payment_method": p.payment_method,
                    "status": p.status,
                    "metadata": p.metadata,
                    "created_at": p.created_at.isoformat(),
                    "completed_at": p.completed_at.isoformat() if p.completed_at else None
                }
                for p in payments
            ]
        }
    
    except Exception as e:
        logger.error(f"Error fetching payment history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch payment history")


@router.get("/{payment_id}/status")
async def check_payment_status(
    payment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Vérifie le statut d'un paiement
    
    **Réponse:**
    ```json
    {
        "payment_id": "abc123",
        "status": "completed",
        "amount": 3.0,
        "currency": "EUR",
        "completed_at": "2025-01-25T10:05:00Z"
    }
    ```
    """
    try:
        payment_service = PaymentService()
        payment = await payment_service.check_payment_status(payment_id, db)
        
        # Vérifier que l'utilisateur a accès à ce paiement
        from sqlalchemy import select
        from models import TeamMember
        
        result = await db.execute(
            select(TeamMember).where(
                TeamMember.team_id == payment.team_id,
                TeamMember.user_id == current_user.id
            )
        )
        membership = result.scalar_one_or_none()
        
        if not membership:
            raise HTTPException(
                status_code=403,
                detail="You don't have access to this payment"
            )
        
        return {
            "payment_id": payment.id,
            "status": payment.status,
            "amount": payment.amount,
            "currency": payment.currency,
            "created_at": payment.created_at.isoformat(),
            "completed_at": payment.completed_at.isoformat() if payment.completed_at else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking payment status: {e}")
        raise HTTPException(status_code=500, detail="Failed to check payment status")


@router.post("/callback")
async def payment_callback(
    request: PaymentCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint de callback pour le backend de paiement externe
    
    **Corps de la requête:**
    ```json
    {
        "external_payment_id": "ext_xyz789",
        "status": "completed",
        "metadata": {
            "transaction_id": "txn_123",
            "provider_reference": "ref_456"
        }
    }
    ```
    
    **Réponse:**
    ```json
    {
        "success": true,
        "payment_id": "abc123",
        "status": "completed"
    }
    ```
    """
    try:
        payment_service = PaymentService()
        payment = await payment_service.handle_payment_callback(
            external_payment_id=request.external_payment_id,
            status=request.status,
            metadata=request.metadata,
            db=db
        )
        
        return {
            "success": True,
            "payment_id": payment.id,
            "status": payment.status
        }
    
    except Exception as e:
        logger.error(f"Error processing payment callback: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.post("/{payment_id}/cancel")
async def cancel_payment(
    payment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Annule un paiement en attente
    
    **Réponse:**
    ```json
    {
        "payment_id": "abc123",
        "status": "cancelled"
    }
    ```
    """
    try:
        payment_service = PaymentService()
        payment = await payment_service.cancel_payment(payment_id, db)
        
        # Vérifier que l'utilisateur a accès à ce paiement
        from sqlalchemy import select
        from models import TeamMember
        
        result = await db.execute(
            select(TeamMember).where(
                TeamMember.team_id == payment.team_id,
                TeamMember.user_id == current_user.id
            )
        )
        membership = result.scalar_one_or_none()
        
        if not membership or membership.role not in ["owner", "admin"]:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to cancel this payment"
            )
        
        return {
            "payment_id": payment.id,
            "status": payment.status
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling payment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
