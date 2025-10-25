from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from db import get_db
from dependencies import get_current_user
from models import User
from services.knowledge_base import KnowledgeBaseService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kb", tags=["knowledge_base"])


class MarkHelpfulRequest(BaseModel):
    helpful: bool


@router.get("/articles")
async def list_articles(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Liste les articles publiés, optionnellement filtrés par catégorie"""
    if category:
        articles = await KnowledgeBaseService.get_articles_by_category(category, db)
    else:
        articles = await KnowledgeBaseService.get_popular_articles(db, limit=50)
    
    return {
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "slug": a.slug,
                "excerpt": a.excerpt,
                "category": a.category,
                "tags": a.tags,
                "view_count": a.view_count,
                "created_at": a.created_at.isoformat()
            }
            for a in articles
        ]
    }


@router.get("/articles/{slug}")
async def get_article(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Récupère un article par son slug"""
    article = await KnowledgeBaseService.get_article_by_slug(slug, db)
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Articles relatés
    related = await KnowledgeBaseService.get_related_articles(article, db)
    
    return {
        "id": article.id,
        "title": article.title,
        "slug": article.slug,
        "content": article.content,
        "excerpt": article.excerpt,
        "category": article.category,
        "tags": article.tags,
        "view_count": article.view_count,
        "helpful_count": article.helpful_count,
        "not_helpful_count": article.not_helpful_count,
        "created_at": article.created_at.isoformat(),
        "related_articles": [
            {
                "id": r.id,
                "title": r.title,
                "slug": r.slug,
                "excerpt": r.excerpt
            }
            for r in related
        ]
    }


@router.get("/search")
async def search_articles(
    q: str,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Recherche des articles"""
    if len(q) < 3:
        raise HTTPException(status_code=400, detail="Query must be at least 3 characters")
    
    articles = await KnowledgeBaseService.search_articles(q, category, db)
    
    return {
        "query": q,
        "results": [
            {
                "id": a.id,
                "title": a.title,
                "slug": a.slug,
                "excerpt": a.excerpt,
                "category": a.category
            }
            for a in articles
        ]
    }


@router.get("/popular")
async def get_popular_articles(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """Récupère les articles les plus populaires"""
    articles = await KnowledgeBaseService.get_popular_articles(db, limit)
    
    return {
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "slug": a.slug,
                "excerpt": a.excerpt,
                "view_count": a.view_count
            }
            for a in articles
        ]
    }


@router.post("/articles/{article_id}/helpful")
async def mark_helpful(
    article_id: str,
    request: MarkHelpfulRequest,
    db: AsyncSession = Depends(get_db),
):
    """Marque un article comme utile ou non"""
    try:
        article = await KnowledgeBaseService.mark_helpful(article_id, request.helpful, db)
        
        return {
            "article_id": article.id,
            "helpful_count": article.helpful_count,
            "not_helpful_count": article.not_helpful_count
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/categories/stats")
async def get_categories_stats(
    db: AsyncSession = Depends(get_db),
):
    """Statistiques par catégorie"""
    stats = await KnowledgeBaseService.get_categories_stats(db)
    return {"categories": stats}
