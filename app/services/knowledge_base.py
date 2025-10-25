from datetime import datetime, timezone
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import KnowledgeBaseArticle
import logging
import re

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Service de gestion de la base de connaissance"""
    
    @staticmethod
    def generate_slug(title: str) -> str:
        """
        Génère un slug à partir d'un titre
        
        Args:
            title: Le titre de l'article
            
        Returns:
            Slug généré
        """
        slug = title.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug[:255]
    
    @staticmethod
    async def create_article(
        title: str,
        content: str,
        category: str,
        db: AsyncSession,
        excerpt: str | None = None,
        tags: list[str] | None = None,
        author_id: int | None = None,
        is_published: bool = False
    ) -> KnowledgeBaseArticle:
        """
        Crée un nouvel article
        
        Args:
            title: Titre
            content: Contenu
            category: Catégorie
            db: Session de base de données
            excerpt: Extrait (optionnel)
            tags: Tags (optionnel)
            author_id: ID de l'auteur
            is_published: Publié ou brouillon
            
        Returns:
            L'article créé
        """
        slug = KnowledgeBaseService.generate_slug(title)
        
        # Vérifier unicité du slug
        result = await db.execute(
            select(KnowledgeBaseArticle).where(
                KnowledgeBaseArticle.slug == slug
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Ajouter un timestamp
            slug = f"{slug}-{int(datetime.now().timestamp())}"
        
        article = KnowledgeBaseArticle(
            title=title,
            slug=slug,
            content=content,
            excerpt=excerpt or content[:200],
            category=category,
            tags=tags or [],
            author_id=author_id,
            is_published=is_published,
            published_at=datetime.now(timezone.utc) if is_published else None
        )
        
        db.add(article)
        await db.commit()
        await db.refresh(article)
        
        logger.info(f"Created KB article: {article.id} - {title}")
        return article
    
    @staticmethod
    async def get_article(
        article_id: str,
        db: AsyncSession,
        increment_view: bool = True
    ) -> KnowledgeBaseArticle | None:
        """
        Récupère un article par son ID
        
        Args:
            article_id: ID de l'article
            db: Session de base de données
            increment_view: Incrémenter le compteur de vues
            
        Returns:
            L'article ou None
        """
        article = await db.get(KnowledgeBaseArticle, article_id)
        
        if article and increment_view:
            article.view_count += 1
            await db.commit()
        
        return article
    
    @staticmethod
    async def get_article_by_slug(
        slug: str,
        db: AsyncSession,
        increment_view: bool = True
    ) -> KnowledgeBaseArticle | None:
        """
        Récupère un article par son slug
        
        Args:
            slug: Slug de l'article
            db: Session de base de données
            increment_view: Incrémenter le compteur de vues
            
        Returns:
            L'article ou None
        """
        result = await db.execute(
            select(KnowledgeBaseArticle).where(
                KnowledgeBaseArticle.slug == slug,
                KnowledgeBaseArticle.is_published == True
            )
        )
        article = result.scalar_one_or_none()
        
        if article and increment_view:
            article.view_count += 1
            await db.commit()
        
        return article
    
    @staticmethod
    async def search_articles(
        query: str,
        category: str | None,
        db: AsyncSession,
        limit: int = 50
    ) -> list[KnowledgeBaseArticle]:
        """
        Recherche des articles
        
        Args:
            query: Texte de recherche
            category: Filtrer par catégorie (optionnel)
            db: Session de base de données
            limit: Nombre maximum de résultats
            
        Returns:
            Liste des articles correspondants
        """
        search = f"%{query}%"
        
        stmt = select(KnowledgeBaseArticle).where(
            KnowledgeBaseArticle.is_published == True,
            or_(
                KnowledgeBaseArticle.title.ilike(search),
                KnowledgeBaseArticle.content.ilike(search),
                KnowledgeBaseArticle.excerpt.ilike(search)
            )
        )
        
        if category:
            stmt = stmt.where(KnowledgeBaseArticle.category == category)
        
        stmt = stmt.order_by(KnowledgeBaseArticle.view_count.desc()).limit(limit)
        
        result = await db.execute(stmt)
        return result.scalars().all()
    
    @staticmethod
    async def get_articles_by_category(
        category: str,
        db: AsyncSession,
        limit: int = 50
    ) -> list[KnowledgeBaseArticle]:
        """
        Récupère les articles d'une catégorie
        
        Args:
            category: Catégorie
            db: Session de base de données
            limit: Nombre maximum d'articles
            
        Returns:
            Liste des articles
        """
        result = await db.execute(
            select(KnowledgeBaseArticle)
            .where(
                KnowledgeBaseArticle.category == category,
                KnowledgeBaseArticle.is_published == True
            )
            .order_by(KnowledgeBaseArticle.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_popular_articles(
        db: AsyncSession,
        limit: int = 10
    ) -> list[KnowledgeBaseArticle]:
        """
        Récupère les articles les plus populaires
        
        Args:
            db: Session de base de données
            limit: Nombre d'articles
            
        Returns:
            Liste des articles populaires
        """
        result = await db.execute(
            select(KnowledgeBaseArticle)
            .where(KnowledgeBaseArticle.is_published == True)
            .order_by(KnowledgeBaseArticle.view_count.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def mark_helpful(
        article_id: str,
        helpful: bool,
        db: AsyncSession
    ) -> KnowledgeBaseArticle:
        """
        Marque un article comme utile ou non
        
        Args:
            article_id: ID de l'article
            helpful: True si utile, False sinon
            db: Session de base de données
            
        Returns:
            L'article mis à jour
        """
        article = await db.get(KnowledgeBaseArticle, article_id)
        if not article:
            raise ValueError(f"Article {article_id} not found")
        
        if helpful:
            article.helpful_count += 1
        else:
            article.not_helpful_count += 1
        
        await db.commit()
        await db.refresh(article)
        
        return article
    
    @staticmethod
    async def get_related_articles(
        article: KnowledgeBaseArticle,
        db: AsyncSession,
        limit: int = 5
    ) -> list[KnowledgeBaseArticle]:
        """
        Récupère les articles similaires/relatés
        
        Args:
            article: L'article de référence
            db: Session de base de données
            limit: Nombre d'articles
            
        Returns:
            Liste des articles relatés
        """
        # Articles de la même catégorie, excluant l'article actuel
        result = await db.execute(
            select(KnowledgeBaseArticle)
            .where(
                KnowledgeBaseArticle.category == article.category,
                KnowledgeBaseArticle.id != article.id,
                KnowledgeBaseArticle.is_published == True
            )
            .order_by(KnowledgeBaseArticle.view_count.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_categories_stats(db: AsyncSession) -> dict:
        """
        Récupère les statistiques par catégorie
        
        Args:
            db: Session de base de données
            
        Returns:
            Statistiques
        """
        result = await db.execute(
            select(
                KnowledgeBaseArticle.category,
                func.count(KnowledgeBaseArticle.id).label('count')
            )
            .where(KnowledgeBaseArticle.is_published == True)
            .group_by(KnowledgeBaseArticle.category)
        )
        
        stats = {}
        for row in result:
            stats[row.category] = row.count
        
        return stats
