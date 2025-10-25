from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Payment, Team, TeamSubscription
from config import get_settings
import httpx
import logging

logger = logging.getLogger(__name__)


class PaymentService:
    """Service de gestion des paiements avec backend externe"""
    
    def __init__(self):
        self.settings = get_settings()
        self.payment_backend_url = getattr(self.settings, 'payment_backend_url', 'http://localhost:8001')
        self.payment_api_key = getattr(self.settings, 'payment_api_key', '')
    
    async def initiate_payment(
        self,
        team_id: str,
        amount: float,
        payment_method: str,
        metadata: dict,
        db: AsyncSession
    ) -> Payment:
        """
        Initialise un paiement
        
        Args:
            team_id: ID de l'équipe
            amount: Montant du paiement
            payment_method: Méthode de paiement (mobile_money ou credit_card)
            metadata: Métadonnées du paiement (plan, description, etc.)
            db: Session de base de données
            
        Returns:
            L'objet Payment créé
        """
        try:
            # Créer le paiement en base de données
            payment = Payment(
                team_id=team_id,
                amount=amount,
                currency="EUR",
                payment_method=payment_method,
                status="pending",
                metadata=metadata
            )
            db.add(payment)
            await db.flush()
            
            # Appeler le backend de paiement externe
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.payment_backend_url}/api/v1/payments/initiate",
                    json={
                        "payment_id": payment.id,
                        "amount": amount,
                        "currency": "EUR",
                        "payment_method": payment_method,
                        "metadata": metadata,
                        "callback_url": f"{self.settings.base_url}/api/payments/callback"
                    },
                    headers={
                        "Authorization": f"Bearer {self.payment_api_key}",
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 201:
                    data = response.json()
                    payment.external_payment_id = data.get("external_payment_id")
                    payment.status = data.get("status", "pending")
                    payment.metadata = {
                        **payment.metadata,
                        "payment_url": data.get("payment_url"),
                        "qr_code": data.get("qr_code")
                    }
                else:
                    logger.error(f"Payment initiation failed: {response.status_code} - {response.text}")
                    payment.status = "failed"
                    payment.metadata = {
                        **payment.metadata,
                        "error": f"Backend returned status {response.status_code}"
                    }
            
            await db.commit()
            logger.info(f"Payment {payment.id} initiated with external ID {payment.external_payment_id}")
            return payment
            
        except Exception as e:
            logger.error(f"Error initiating payment: {e}")
            await db.rollback()
            raise
    
    async def check_payment_status(
        self,
        payment_id: str,
        db: AsyncSession
    ) -> Payment:
        """
        Vérifie le statut d'un paiement auprès du backend externe
        
        Args:
            payment_id: ID du paiement
            db: Session de base de données
            
        Returns:
            L'objet Payment mis à jour
        """
        try:
            payment = await db.get(Payment, payment_id)
            if not payment:
                raise ValueError(f"Payment {payment_id} not found")
            
            if not payment.external_payment_id:
                logger.warning(f"Payment {payment_id} has no external payment ID")
                return payment
            
            # Vérifier le statut auprès du backend
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.payment_backend_url}/api/v1/payments/{payment.external_payment_id}/status",
                    headers={
                        "Authorization": f"Bearer {self.payment_api_key}"
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    old_status = payment.status
                    payment.status = data.get("status", payment.status)
                    
                    if payment.status == "completed" and old_status != "completed":
                        payment.completed_at = datetime.now(timezone.utc)
                        # Activer le plan si c'est un paiement pour upgrade
                        if payment.metadata.get("plan_upgrade"):
                            await self._activate_plan_upgrade(payment, db)
                    
                    await db.commit()
                    logger.info(f"Payment {payment_id} status updated to {payment.status}")
                else:
                    logger.error(f"Failed to check payment status: {response.status_code}")
            
            return payment
            
        except Exception as e:
            logger.error(f"Error checking payment status: {e}")
            raise
    
    async def handle_payment_callback(
        self,
        external_payment_id: str,
        status: str,
        metadata: dict,
        db: AsyncSession
    ) -> Payment:
        """
        Traite un callback du backend de paiement
        
        Args:
            external_payment_id: ID externe du paiement
            status: Nouveau statut du paiement
            metadata: Métadonnées supplémentaires
            db: Session de base de données
            
        Returns:
            L'objet Payment mis à jour
        """
        try:
            # Trouver le paiement par l'ID externe
            result = await db.execute(
                select(Payment).where(Payment.external_payment_id == external_payment_id)
            )
            payment = result.scalar_one_or_none()
            
            if not payment:
                raise ValueError(f"Payment with external ID {external_payment_id} not found")
            
            old_status = payment.status
            payment.status = status
            payment.metadata = {**payment.metadata, **metadata}
            
            if status == "completed" and old_status != "completed":
                payment.completed_at = datetime.now(timezone.utc)
                # Activer le plan si c'est un paiement pour upgrade
                if payment.metadata.get("plan_upgrade"):
                    await self._activate_plan_upgrade(payment, db)
            
            await db.commit()
            logger.info(f"Payment callback processed for {external_payment_id}: status={status}")
            return payment
            
        except Exception as e:
            logger.error(f"Error handling payment callback: {e}")
            await db.rollback()
            raise
    
    async def _activate_plan_upgrade(
        self,
        payment: Payment,
        db: AsyncSession
    ) -> None:
        """
        Active le changement de plan après un paiement réussi
        
        Args:
            payment: Le paiement
            db: Session de base de données
        """
        try:
            from services.pricing import PricingService
            
            plan_name = payment.metadata.get("new_plan")
            if not plan_name:
                logger.warning(f"Payment {payment.id} has plan_upgrade but no new_plan in metadata")
                return
            
            if plan_name == "pay_as_you_go":
                team = await db.get(Team, payment.team_id)
                if team:
                    await PricingService.assign_pay_as_you_go_plan_to_team(team, db)
                    logger.info(f"Team {payment.team_id} upgraded to Pay as You Go plan")
        
        except Exception as e:
            logger.error(f"Error activating plan upgrade: {e}")
            raise
    
    async def get_payment_history(
        self,
        team_id: str,
        db: AsyncSession,
        limit: int = 50
    ) -> list[Payment]:
        """
        Récupère l'historique des paiements d'une équipe
        
        Args:
            team_id: ID de l'équipe
            limit: Nombre maximum de paiements à retourner
            db: Session de base de données
            
        Returns:
            Liste des paiements
        """
        result = await db.execute(
            select(Payment)
            .where(Payment.team_id == team_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def cancel_payment(
        self,
        payment_id: str,
        db: AsyncSession
    ) -> Payment:
        """
        Annule un paiement en attente
        
        Args:
            payment_id: ID du paiement
            db: Session de base de données
            
        Returns:
            L'objet Payment mis à jour
        """
        try:
            payment = await db.get(Payment, payment_id)
            if not payment:
                raise ValueError(f"Payment {payment_id} not found")
            
            if payment.status not in ["pending", "processing"]:
                raise ValueError(f"Cannot cancel payment with status {payment.status}")
            
            # Annuler auprès du backend si nécessaire
            if payment.external_payment_id:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self.payment_backend_url}/api/v1/payments/{payment.external_payment_id}/cancel",
                        headers={
                            "Authorization": f"Bearer {self.payment_api_key}"
                        }
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Failed to cancel payment on backend: {response.status_code}")
            
            payment.status = "cancelled"
            await db.commit()
            logger.info(f"Payment {payment_id} cancelled")
            return payment
            
        except Exception as e:
            logger.error(f"Error cancelling payment: {e}")
            await db.rollback()
            raise
