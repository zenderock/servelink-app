from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from db import get_db
from dependencies import templates, TemplateResponse, get_current_user
from models import User
from services.knowledge_base import KnowledgeBaseService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge_base_pages"])


@router.get("/help", name="kb_index", response_class=HTMLResponse)
async def kb_index(
    request: Request,
    query: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Page principale Knowledge Base"""
    
    # Récupérer les catégories avec comptage
    categories_data = await KnowledgeBaseService.get_categories_stats(db)
    
    # Formater les catégories
    category_names = {
        'getting_started': 'Getting Started',
        'deployment': 'Deployment',
        'billing': 'Billing',
        'troubleshooting': 'Troubleshooting',
        'api': 'API & Integrations',
        'other': 'Other'
    }
    
    category_descriptions = {
        'getting_started': 'Learn the basics and get started quickly',
        'deployment': 'Deploy and manage your applications',
        'billing': 'Subscription plans and payments',
        'troubleshooting': 'Fix common issues and errors',
        'api': 'API documentation and integrations',
        'other': 'Additional resources and guides'
    }
    
    categories = []
    for cat_slug, count in categories_data.items():
        categories.append({
            'slug': cat_slug,
            'name': category_names.get(cat_slug, cat_slug.title()),
            'description': category_descriptions.get(cat_slug, ''),
            'article_count': count
        })
    
    # Récupérer les articles populaires
    popular_articles = await KnowledgeBaseService.get_popular_articles(db, limit=5)
    
    # Ajouter les noms de catégories
    for article in popular_articles:
        article.category_name = category_names.get(article.category, article.category.title())
    
    return templates.TemplateResponse(
        request,
        "knowledge_base/pages/index.html",
        {
            "categories": categories,
            "popular_articles": popular_articles,
            "query": query,
        }
    )


@router.get("/help/search", name="kb_search", response_class=HTMLResponse)
async def kb_search(
    request: Request,
    q: str,
    db: AsyncSession = Depends(get_db),
):
    """Recherche dans la knowledge base"""
    
    # Rechercher les articles
    articles = await KnowledgeBaseService.search_articles(q, db, limit=20)
    
    return templates.TemplateResponse(
        request,
        "knowledge_base/pages/search.html",
        {
            "query": q,
            "articles": articles,
            "count": len(articles),
        }
    )


@router.get("/help/category/{category}", name="kb_category", response_class=HTMLResponse)
async def kb_category(
    request: Request,
    category: str,
    db: AsyncSession = Depends(get_db),
):
    """Page catégorie"""
    
    # Récupérer les articles de la catégorie
    articles = await KnowledgeBaseService.get_articles_by_category(category, db)
    
    if not articles:
        raise HTTPException(status_code=404, detail="Category not found")
    
    category_names = {
        'getting_started': 'Getting Started',
        'deployment': 'Deployment',
        'billing': 'Billing',
        'troubleshooting': 'Troubleshooting',
        'api': 'API & Integrations',
        'other': 'Other'
    }
    
    return templates.TemplateResponse(
        request,
        "knowledge_base/pages/category.html",
        {
            "category": category,
            "category_name": category_names.get(category, category.title()),
            "articles": articles,
        }
    )


@router.get("/help/article/{slug}", name="kb_article", response_class=HTMLResponse)
async def kb_article(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Page article détaillé"""
    
    # Récupérer l'article
    article = await KnowledgeBaseService.get_article_by_slug(slug, db)
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Incrémenter le compteur de vues
    await KnowledgeBaseService.increment_view_count(article.id, db)
    
    # Récupérer les articles reliés
    related_articles = await KnowledgeBaseService.get_related_articles(
        article.id,
        article.category,
        db,
        limit=3
    )
    
    return templates.TemplateResponse(
        request,
        "knowledge_base/pages/article.html",
        {
            "article": article,
            "related_articles": related_articles,
        }
    )


@router.post("/help/article/{article_id}/feedback", name="kb_feedback")
async def kb_feedback(
    request: Request,
    article_id: str,
    helpful: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Enregistrer le feedback d'un article"""
    
    try:
        is_helpful = helpful == "yes"
        await KnowledgeBaseService.add_feedback(article_id, is_helpful, db)
        
        request.session["flash_messages"] = [
            {
                "type": "success",
                "message": "Thank you for your feedback!"
            }
        ]
    except Exception as e:
        logger.error(f"Error recording feedback: {e}")
        request.session["flash_messages"] = [
            {
                "type": "error",
                "message": "Failed to record feedback"
            }
        ]
    
    # Récupérer l'article pour obtenir le slug
    article = await KnowledgeBaseService.get_article_by_id(article_id, db)
    if article:
        return RedirectResponse(
            url=f"/help/article/{article.slug}",
            status_code=303
        )
    
    return RedirectResponse(url="/help", status_code=303)
