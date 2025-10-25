from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from db import get_db
from dependencies import get_current_user, get_team_by_slug
from models import User, Team, TeamMember
from services.additional_resources import AdditionalResourceService
from services.payment import PaymentService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resources", tags=["resources"])


class PurchaseResourceRequest(BaseModel):
    resource_type: str
    quantity: int


@router.get("/{team_slug}/available")
async def get_available_resources(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Récupère les ressources disponibles à l'achat
    
    **Réponse:**
    ```json
    {
        "resources": [
            {
                "type": "ram",
                "name": "RAM additionnelle",
                "unit": "500 MB",
                "price": 1.0,
                "currency": "EUR",
                "description": "Ajoutez 500 MB de RAM à votre plan"
            }
        ]
    }
    ```
    """
    team, _ = team_and_membership
    
    # Vérifier que c'est un plan Pro
    if not team.current_plan or team.current_plan.name != "pay_as_you_go":
        raise HTTPException(
            status_code=403,
            detail="Additional resources are only available for Pro plan"
        )
    
    resources = []
    for resource_type in ["ram", "cpu", "traffic", "storage"]:
        info = AdditionalResourceService.get_resource_description(resource_type)
        resources.append({
            "type": resource_type,
            **info
        })
    
    return {"resources": resources}


@router.post("/{team_slug}/purchase")
async def purchase_resource(
    team_slug: str,
    request: PurchaseResourceRequest,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Achète une ressource additionnelle
    
    **Corps de la requête:**
    ```json
    {
        "resource_type": "ram",
        "quantity": 2
    }
    ```
    
    **Réponse:**
    ```json
    {
        "payment_id": "pm_abc123",
        "resource_id": "res_xyz789",
        "amount": 2.0,
        "payment_url": "https://pay.example.com/xyz789"
    }
    ```
    """
    team, membership = team_and_membership
    
    # Vérifier les permissions
    if membership.role not in ["owner", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only team owners and admins can purchase resources"
        )
    
    # Vérifier que c'est un plan Pro
    if not team.current_plan or team.current_plan.name != "pay_as_you_go":
        raise HTTPException(
            status_code=403,
            detail="Additional resources are only available for Pro plan"
        )
    
    # Vérifier la quantité
    if request.quantity < 1 or request.quantity > 100:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be between 1 and 100"
        )
    
    try:
        # Calculer le prix
        price = AdditionalResourceService.calculate_price(
            request.resource_type,
            request.quantity
        )
        
        # Initier le paiement
        payment_service = PaymentService()
        payment = await payment_service.initiate_payment(
            team_id=team.id,
            amount=price,
            payment_method="mobile_money",  # À adapter selon les besoins
            metadata={
                "description": f"Purchase {request.quantity}x {request.resource_type}",
                "resource_purchase": True,
                "resource_type": request.resource_type,
                "quantity": request.quantity
            },
            db=db
        )
        
        # Créer la ressource (sera activée après paiement)
        resource = await AdditionalResourceService.purchase_resource(
            team_id=team.id,
            resource_type=request.resource_type,
            quantity=request.quantity,
            payment_id=payment.id,
            db=db
        )
        
        return {
            "payment_id": payment.id,
            "resource_id": resource.id,
            "amount": price,
            "payment_url": payment.metadata.get("payment_url"),
            "qr_code": payment.metadata.get("qr_code")
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error purchasing resource: {e}")
        raise HTTPException(status_code=500, detail="Failed to purchase resource")


@router.get("/{team_slug}/list")
async def list_team_resources(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Liste les ressources d'une équipe
    
    **Réponse:**
    ```json
    {
        "resources": [
            {
                "id": "res_123",
                "resource_type": "ram",
                "quantity": 2,
                "unit_price": 1.0,
                "status": "active",
                "expires_at": "2025-02-25T10:00:00Z"
            }
        ],
        "totals": {
            "ram_mb": 1000,
            "cpu_cores": 2.0,
            "traffic_gb": 20,
            "storage_gb": 10
        }
    }
    ```
    """
    team, _ = team_and_membership
    
    resources = await AdditionalResourceService.get_team_resources(
        team.id, db, active_only=False
    )
    
    totals = await AdditionalResourceService.get_total_additional_resources(
        team.id, db
    )
    
    return {
        "resources": [
            {
                "id": r.id,
                "resource_type": r.resource_type,
                "quantity": r.quantity,
                "unit_price": r.unit_price,
                "currency": r.currency,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None
            }
            for r in resources
        ],
        "totals": totals
    }


@router.delete("/{team_slug}/cancel/{resource_id}")
async def cancel_resource(
    team_slug: str,
    resource_id: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Annule une ressource additionnelle
    
    **Réponse:**
    ```json
    {
        "resource_id": "res_123",
        "status": "cancelled"
    }
    ```
    """
    team, membership = team_and_membership
    
    # Vérifier les permissions
    if membership.role not in ["owner", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only team owners and admins can cancel resources"
        )
    
    try:
        resource = await AdditionalResourceService.cancel_resource(
            resource_id, db
        )
        
        # Vérifier que la ressource appartient à l'équipe
        if resource.team_id != team.id:
            raise HTTPException(
                status_code=403,
                detail="This resource does not belong to your team"
            )
        
        return {
            "resource_id": resource.id,
            "status": resource.status
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error cancelling resource: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel resource")


@router.get("/{team_slug}/limits")
async def get_team_limits(
    team_slug: str,
    current_user: User = Depends(get_current_user),
    team_and_membership: tuple[Team, TeamMember] = Depends(get_team_by_slug),
    db: AsyncSession = Depends(get_db),
):
    """
    Récupère les limites totales d'une équipe (plan + ressources additionnelles)
    
    **Réponse:**
    ```json
    {
        "cpu_cores": 6.0,
        "memory_mb": 6644,
        "traffic_gb": 30,
        "storage_mb": 20480,
        "plan_limits": {
            "cpu_cores": 4.0,
            "memory_mb": 6144,
            "traffic_gb": 10,
            "storage_mb": 10240
        },
        "additional_resources": {
            "ram_mb": 500,
            "cpu_cores": 2.0,
            "traffic_gb": 20,
            "storage_gb": 10
        }
    }
    ```
    """
    team, _ = team_and_membership
    
    limits = await AdditionalResourceService.get_team_limits_with_additional(
        team, db
    )
    
    return limits
