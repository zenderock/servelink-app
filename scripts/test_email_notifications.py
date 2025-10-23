#!/usr/bin/env python3
"""
Script de test pour vérifier les notifications email de désactivation de projets
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
from services.notification import DeploymentNotificationService
from config import get_settings


async def test_email_notifications():
    """Test complet des notifications email"""
    async with AsyncSessionLocal() as db:
        try:
            print("📧 Test des notifications email de désactivation de projets")
            print("=" * 60)
            
            # 1. Créer un plan gratuit
            print("1. Création du plan gratuit...")
            free_plan = await PricingService.get_default_free_plan(db)
            print(f"   ✅ Plan gratuit créé: {free_plan.name}")
            
            # 2. Créer un utilisateur et une équipe
            print("2. Création de l'utilisateur et de l'équipe...")
            user = User(
                email="test-notifications@example.com",
                username="testnotifications",
                email_verified=True,
                status="active"
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
            team = Team(
                name="Test Notifications Team",
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
                name="Test Email Project",
                repo_id=54321,
                repo_full_name="test/email-repo",
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
                hostname="test-email.example.com",
                type="route",
                status="active"
            )
            db.add(domain)
            await db.commit()
            
            print(f"   ✅ Projet créé: {project.name} (inactif depuis 6 jours)")
            
            # 4. Tester la notification de désactivation temporaire
            print("4. Test de la notification de désactivation temporaire...")
            settings = get_settings()
            
            # Mock OneSignal pour éviter d'envoyer de vrais emails
            with patch('app.services.notification.OneSignalService') as mock_onesignal:
                mock_onesignal.return_value.send_email = AsyncMock(return_value=True)
                
                async with DeploymentNotificationService(settings) as notification_service:
                    success = await notification_service.send_project_disabled_notification(project, user, team)
                    
                    if success:
                        print("   ✅ Notification de désactivation temporaire envoyée")
                    else:
                        print("   ❌ Échec de l'envoi de la notification")
                        return False
            
            # 5. Tester la notification de désactivation permanente
            print("5. Test de la notification de désactivation permanente...")
            project.status = "permanently_disabled"
            project.deactivated_at = datetime.now(timezone.utc)
            await db.commit()
            
            with patch('app.services.notification.OneSignalService') as mock_onesignal:
                mock_onesignal.return_value.send_email = AsyncMock(return_value=True)
                
                async with DeploymentNotificationService(settings) as notification_service:
                    success = await notification_service.send_project_permanently_disabled_notification(project, user, team)
                    
                    if success:
                        print("   ✅ Notification de désactivation permanente envoyée")
                    else:
                        print("   ❌ Échec de l'envoi de la notification")
                        return False
            
            # 6. Tester l'intégration complète
            print("6. Test de l'intégration complète...")
            # Créer un autre projet pour tester l'intégration
            project2 = Project(
                name="Test Integration Project",
                repo_id=65432,
                repo_full_name="test/integration-repo",
                github_installation_id=1,
                team_id=team.id,
                status="active",
                last_traffic_at=six_days_ago
            )
            db.add(project2)
            await db.commit()
            await db.refresh(project2)
            
            # Tester la désactivation avec notification
            with patch('app.services.notification.OneSignalService') as mock_onesignal:
                mock_onesignal.return_value.send_email = AsyncMock(return_value=True)
                
                await ProjectMonitoringService.check_inactive_projects(db)
                
                await db.refresh(project2)
                if project2.status == "inactive":
                    print("   ✅ Désactivation avec notification intégrée")
                else:
                    print("   ❌ Échec de l'intégration")
                    return False
            
            print("\n🎉 Tous les tests de notifications email sont passés avec succès!")
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
                "DELETE FROM project WHERE name LIKE 'Test%Project%'"
            )
            
            # Supprimer les équipes de test
            await db.execute(
                "DELETE FROM team WHERE name = 'Test Notifications Team'"
            )
            
            # Supprimer les utilisateurs de test
            await db.execute(
                "DELETE FROM user WHERE email = 'test-notifications@example.com'"
            )
            
            await db.commit()
            print("🧹 Données de test nettoyées")
            
        except Exception as e:
            print(f"Erreur lors du nettoyage: {e}")
            await db.rollback()


if __name__ == "__main__":
    print("🚀 Démarrage des tests de notifications email")
    
    # Importer patch ici pour éviter les erreurs d'import
    from unittest.mock import patch, AsyncMock
    
    # Exécuter les tests
    success = asyncio.run(test_email_notifications())
    
    if success:
        # Nettoyer les données de test
        asyncio.run(cleanup_test_data())
        print("\n✅ Tests de notifications email terminés avec succès!")
        sys.exit(0)
    else:
        print("\n❌ Tests de notifications email échoués!")
        sys.exit(1)
