#!/usr/bin/env python3
"""
Script pour initialiser last_traffic_at pour les projets existants
"""
import asyncio
import sys
import os

# Ajouter le répertoire app au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from db import AsyncSessionLocal
from models import Project
from sqlalchemy import select, update


async def init_project_traffic():
    """Initialise last_traffic_at pour tous les projets existants"""
    async with AsyncSessionLocal() as db:
        try:
            # Récupérer tous les projets sans last_traffic_at
            result = await db.execute(
                select(Project).where(Project.last_traffic_at.is_(None))
            )
            projects = result.scalars().all()
            
            print(f"Trouvé {len(projects)} projets sans last_traffic_at")
            
            # Mettre à jour chaque projet
            for project in projects:
                await db.execute(
                    update(Project)
                    .where(Project.id == project.id)
                    .values(last_traffic_at=project.updated_at)
                )
                print(f"Initialisé last_traffic_at pour le projet {project.name} ({project.id})")
            
            await db.commit()
            print("Initialisation terminée avec succès")
            
        except Exception as e:
            print(f"Erreur lors de l'initialisation: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(init_project_traffic())
