#!/usr/bin/env python3
"""
Script pour synchroniser les valeurs de project.config vers les nouvelles colonnes
allocated_cpu_cores et allocated_memory_mb
"""

import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire app au path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Project
from config import get_settings


async def sync_project_resources():
    """Synchroniser les ressources des projets depuis config vers les colonnes dédiées"""
    settings = get_settings()
    
    # Créer la connexion à la base de données
    database_url = f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@localhost:5432/{settings.postgres_db}"
    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        # Récupérer tous les projets qui ont des ressources dans config
        result = await db.execute(
            select(Project).where(
                Project.config.has_key('cpus') | Project.config.has_key('memory')
            )
        )
        projects = result.scalars().all()
        
        print(f"Found {len(projects)} projects with resource configuration")
        
        updated_count = 0
        for project in projects:
            updated = False
            
            # Synchroniser CPU
            if 'cpus' in project.config and project.config['cpus'] is not None:
                if project.allocated_cpu_cores != project.config['cpus']:
                    project.allocated_cpu_cores = project.config['cpus']
                    updated = True
                    print(f"Project {project.name}: CPU {project.config['cpus']}")
            
            # Synchroniser Memory
            if 'memory' in project.config and project.config['memory'] is not None:
                if project.allocated_memory_mb != project.config['memory']:
                    project.allocated_memory_mb = project.config['memory']
                    updated = True
                    print(f"Project {project.name}: Memory {project.config['memory']}MB")
            
            if updated:
                updated_count += 1
        
        if updated_count > 0:
            await db.commit()
            print(f"Updated {updated_count} projects")
        else:
            print("No projects needed updating")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(sync_project_resources())
