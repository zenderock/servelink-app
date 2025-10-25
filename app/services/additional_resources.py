from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import AdditionalResource, Team, Payment
import logging

logger = logging.getLogger(__name__)


# Prix unitaires selon pricing-specs.json
RESOURCE_PRICES = {
    "ram": {
        "unit": "500_mb",
        "price_per_unit": 1.0,
        "currency": "EUR"
    },
    "cpu": {
        "unit": "1_cpu",
        "price_per_unit": 2.0,
        "currency": "EUR"
    },
    "traffic": {
        "unit": "10_gb",
        "price_per_unit": 1.0,
        "currency": "EUR"
    },
    "storage": {
        "unit": "10_gb",
        "price_per_unit": 1.0,
        "currency": "EUR"
    }
}


class AdditionalResourceService:
    """Service de gestion des ressources additionnelles"""
    
    @staticmethod
    async def purchase_resource(
        team_id: str,
        resource_type: str,
        quantity: int,
        payment_id: str | None,
        db: AsyncSession
    ) -> AdditionalResource:
        """
        Achète une ressource additionnelle
        
        Args:
            team_id: ID de l'équipe
            resource_type: Type de ressource (ram, cpu, traffic, storage)
            quantity: Quantité achetée
            payment_id: ID du paiement associé
            db: Session de base de données
            
        Returns:
            La ressource additionnelle créée
        """
        if resource_type not in RESOURCE_PRICES:
            raise ValueError(f"Invalid resource type: {resource_type}")
        
        pricing = RESOURCE_PRICES[resource_type]
        unit_price = pricing["price_per_unit"]
        
        # Les ressources expirent après 30 jours (abonnement mensuel)
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        
        resource = AdditionalResource(
            team_id=team_id,
            resource_type=resource_type,
            quantity=quantity,
            unit_price=unit_price,
            currency=pricing["currency"],
            payment_id=payment_id,
            status="active",
            expires_at=expires_at
        )
        
        db.add(resource)
        await db.commit()
        await db.refresh(resource)
        
        logger.info(f"Purchased {quantity}x {resource_type} for team {team_id}")
        return resource
    
    @staticmethod
    async def get_team_resources(
        team_id: str,
        db: AsyncSession,
        active_only: bool = True
    ) -> list[AdditionalResource]:
        """
        Récupère les ressources d'une équipe
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            active_only: Ne retourner que les ressources actives
            
        Returns:
            Liste des ressources
        """
        query = select(AdditionalResource).where(
            AdditionalResource.team_id == team_id
        )
        
        if active_only:
            query = query.where(AdditionalResource.status == "active")
        
        result = await db.execute(query.order_by(AdditionalResource.created_at.desc()))
        return result.scalars().all()
    
    @staticmethod
    async def get_total_additional_resources(
        team_id: str,
        db: AsyncSession
    ) -> dict:
        """
        Calcule le total des ressources additionnelles actives d'une équipe
        
        Args:
            team_id: ID de l'équipe
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les totaux par type de ressource
        """
        result = await db.execute(
            select(
                AdditionalResource.resource_type,
                func.sum(AdditionalResource.quantity).label('total')
            )
            .where(
                AdditionalResource.team_id == team_id,
                AdditionalResource.status == "active"
            )
            .group_by(AdditionalResource.resource_type)
        )
        
        totals = {row.resource_type: row.total for row in result}
        
        return {
            "ram_mb": totals.get("ram", 0) * 500,  # 500 MB par unité
            "cpu_cores": totals.get("cpu", 0) * 1.0,  # 1 CPU par unité
            "traffic_gb": totals.get("traffic", 0) * 10,  # 10 GB par unité
            "storage_gb": totals.get("storage", 0) * 10  # 10 GB par unité
        }
    
    @staticmethod
    async def cancel_resource(
        resource_id: str,
        db: AsyncSession
    ) -> AdditionalResource:
        """
        Annule une ressource additionnelle
        
        Args:
            resource_id: ID de la ressource
            db: Session de base de données
            
        Returns:
            La ressource mise à jour
        """
        resource = await db.get(AdditionalResource, resource_id)
        if not resource:
            raise ValueError(f"Resource {resource_id} not found")
        
        if resource.status != "active":
            raise ValueError(f"Cannot cancel resource with status {resource.status}")
        
        resource.status = "cancelled"
        await db.commit()
        await db.refresh(resource)
        
        logger.info(f"Cancelled resource {resource_id}")
        return resource
    
    @staticmethod
    async def expire_resources(db: AsyncSession) -> int:
        """
        Expire les ressources dont la date d'expiration est dépassée
        
        Args:
            db: Session de base de données
            
        Returns:
            Nombre de ressources expirées
        """
        now = datetime.now(timezone.utc)
        
        result = await db.execute(
            select(AdditionalResource).where(
                AdditionalResource.status == "active",
                AdditionalResource.expires_at < now
            )
        )
        resources = result.scalars().all()
        
        count = 0
        for resource in resources:
            resource.status = "expired"
            count += 1
        
        if count > 0:
            await db.commit()
            logger.info(f"Expired {count} resources")
        
        return count
    
    @staticmethod
    def calculate_price(resource_type: str, quantity: int) -> float:
        """
        Calcule le prix pour une ressource
        
        Args:
            resource_type: Type de ressource
            quantity: Quantité
            
        Returns:
            Prix total en EUR
        """
        if resource_type not in RESOURCE_PRICES:
            raise ValueError(f"Invalid resource type: {resource_type}")
        
        return RESOURCE_PRICES[resource_type]["price_per_unit"] * quantity
    
    @staticmethod
    def get_resource_description(resource_type: str) -> dict:
        """
        Retourne la description d'une ressource
        
        Args:
            resource_type: Type de ressource
            
        Returns:
            Dictionnaire avec les informations de la ressource
        """
        descriptions = {
            "ram": {
                "name": "RAM additionnelle",
                "unit": "500 MB",
                "description": "Ajoutez 500 MB de RAM à votre plan",
                "icon": "memory"
            },
            "cpu": {
                "name": "CPU additionnel",
                "unit": "1 CPU",
                "description": "Ajoutez 1 cœur CPU à votre plan",
                "icon": "cpu"
            },
            "traffic": {
                "name": "Trafic additionnel",
                "unit": "10 GB",
                "description": "Ajoutez 10 GB de trafic mensuel",
                "icon": "network"
            },
            "storage": {
                "name": "Stockage additionnel",
                "unit": "10 GB",
                "description": "Ajoutez 10 GB d'espace disque",
                "icon": "storage"
            }
        }
        
        if resource_type not in descriptions:
            raise ValueError(f"Invalid resource type: {resource_type}")
        
        result = descriptions[resource_type].copy()
        result["price"] = RESOURCE_PRICES[resource_type]["price_per_unit"]
        result["currency"] = RESOURCE_PRICES[resource_type]["currency"]
        
        return result
    
    @staticmethod
    async def get_team_limits_with_additional(
        team: Team,
        db: AsyncSession
    ) -> dict:
        """
        Calcule les limites totales d'une équipe (plan + ressources additionnelles)
        
        Args:
            team: L'équipe
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les limites totales
        """
        plan = team.current_plan
        if not plan:
            return {}
        
        additional = await AdditionalResourceService.get_total_additional_resources(
            team.id, db
        )
        
        return {
            "cpu_cores": plan.max_cpu_cores + additional["cpu_cores"],
            "memory_mb": plan.max_memory_mb + additional["ram_mb"],
            "traffic_gb": plan.max_traffic_gb_per_month + additional["traffic_gb"],
            "storage_mb": (plan.max_storage_mb // 1024 + additional["storage_gb"]) * 1024,  # Convertir en MB
            "plan_limits": {
                "cpu_cores": plan.max_cpu_cores,
                "memory_mb": plan.max_memory_mb,
                "traffic_gb": plan.max_traffic_gb_per_month,
                "storage_mb": plan.max_storage_mb
            },
            "additional_resources": additional
        }
