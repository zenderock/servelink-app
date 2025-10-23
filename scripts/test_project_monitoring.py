#!/usr/bin/env python3
"""
Script de test pour vérifier le système de monitoring des projets
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

# Ajouter le répertoire app au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from db import AsyncSessionLocal
from models import Project, Team, User, TeamSubscription, Domain
from services.project_monitoring import ProjectMonitoringService
from services.pricing import PricingService


async def test_project_monitoring():
    """Test complet du système de monitoring"""
    async with AsyncSessionLocal() as db:
        try:
            print("🧪 Test du système de monitoring des projets")
            print("=" * 50)
            
            # 1. Créer un plan gratuit
            print("1. Création du plan gratuit...")
            free_plan = await PricingService.get_default_free_plan(db)
            print(f"   ✅ Plan gratuit créé: {free_plan.name}")
            
            # 2. Créer un utilisateur et une équipe
            print("2. Création de l'utilisateur et de l'équipe...")
            user = User(
                email="test@example.com",
                username="testuser",
                email_verified=True,
                status="active"
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
            team = Team(
                name="Test Team",
                created_by_user_id=user.id,
                status="active"
            )
            db.add(team)
            await db.commit()
            await db.refresh(team)
            
            # Assigner le plan gratuit
            subscription = TeamSubscription(
                team_id=team.id,
                plan_id=free_plan.id,
                status="active"
            )
            db.add(subscription)
            await db.commit()
            
            print(f"   ✅ Utilisateur et équipe créés: {team.name}")
            
            # 3. Créer un projet inactif
            print("3. Création d'un projet inactif...")
            six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
            project = Project(
                name="Test Project Inactif",
                repo_id=12345,
                repo_full_name="test/inactive-repo",
                github_installation_id=1,
                team_id=team.id,
                status="active",
                last_traffic_at=six_days_ago
            )
            db.add(project)
            await db.commit()
            await db.refresh(project)
            
            # Créer un domaine pour le projet
            domain = Domain(
                project_id=project.id,
                hostname="test-inactive.example.com",
                type="route",
                status="active"
            )
            db.add(domain)
            await db.commit()
            
            print(f"   ✅ Projet créé: {project.name} (inactif depuis 6 jours)")
            
            # 4. Tester la désactivation automatique
            print("4. Test de la désactivation automatique...")
            await ProjectMonitoringService.check_inactive_projects(db)
            
            await db.refresh(project)
            if project.status == "inactive":
                print("   ✅ Projet désactivé automatiquement")
            else:
                print("   ❌ Projet non désactivé")
                return False
            
            # 5. Tester la réactivation
            print("5. Test de la réactivation...")
            success = await ProjectMonitoringService.reactivate_project(project, db)
            
            await db.refresh(project)
            await db.refresh(domain)
            
            if success and project.status == "active" and domain.status == "active":
                print("   ✅ Projet réactivé avec succès")
            else:
                print("   ❌ Échec de la réactivation")
                return False
            
            # 6. Tester l'enregistrement du trafic
            print("6. Test de l'enregistrement du trafic...")
            await ProjectMonitoringService.record_traffic(project, db)
            
            await db.refresh(project)
            if project.last_traffic_at is not None:
                print("   ✅ Trafic enregistré avec succès")
            else:
                print("   ❌ Échec de l'enregistrement du trafic")
                return False
            
            # 7. Tester la désactivation permanente
            print("7. Test de la désactivation permanente...")
            # Simuler un projet inactif depuis 8 jours
            eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
            project.status = "inactive"
            project.deactivated_at = eight_days_ago
            await db.commit()
            
            await ProjectMonitoringService.check_permanently_disabled_projects(db)
            
            await db.refresh(project)
            if project.status == "permanently_disabled":
                print("   ✅ Projet désactivé définitivement")
            else:
                print("   ❌ Projet non désactivé définitivement")
                return False
            
            # 8. Tester que la réactivation est impossible
            print("8. Test de l'impossibilité de réactivation...")
            success = await ProjectMonitoringService.reactivate_project(project, db)
            
            if not success:
                print("   ✅ Réactivation correctement bloquée")
            else:
                print("   ❌ Réactivation autorisée à tort")
                return False
            
            print("\n🎉 Tous les tests sont passés avec succès!")
            return True
            
        except Exception as e:
            print(f"\n❌ Erreur lors des tests: {e}")
            await db.rollback()
            return False


async def cleanup_test_data():
    """Nettoie les données de test"""
    async with AsyncSessionLocal() as db:
        try:
            # Supprimer les projets de test
            await db.execute(
                "DELETE FROM project WHERE name LIKE 'Test Project%'"
            )
            
            # Supprimer les équipes de test
            await db.execute(
                "DELETE FROM team WHERE name = 'Test Team'"
            )
            
            # Supprimer les utilisateurs de test
            await db.execute(
                "DELETE FROM user WHERE email = 'test@example.com'"
            )
            
            await db.commit()
            print("🧹 Données de test nettoyées")
            
        except Exception as e:
            print(f"Erreur lors du nettoyage: {e}")
            await db.rollback()


if __name__ == "__main__":
    print("🚀 Démarrage des tests de monitoring des projets")
    
    # Exécuter les tests
    success = asyncio.run(test_project_monitoring())
    
    if success:
        # Nettoyer les données de test
        asyncio.run(cleanup_test_data())
        print("\n✅ Tests terminés avec succès!")
        sys.exit(0)
    else:
        print("\n❌ Tests échoués!")
        sys.exit(1)
