import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Project, Team, TeamMember, User, TeamSubscription, SubscriptionPlan, Domain
from services.project_monitoring import ProjectMonitoringService
from services.pricing import PricingService
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_check_inactive_projects(db: AsyncSession):
    """Test de désactivation après 5 jours d'inactivité"""
    # Créer un plan gratuit
    free_plan = await PricingService.get_default_free_plan(db)
    
    # Créer un utilisateur et une équipe
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
    
    # Assigner le plan gratuit à l'équipe
    subscription = TeamSubscription(
        team_id=team.id,
        plan_id=free_plan.id,
        status="active"
    )
    db.add(subscription)
    await db.commit()
    
    # Créer un projet inactif depuis 6 jours
    six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id=team.id,
        status="active",
        last_traffic_at=six_days_ago
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Exécuter la vérification avec mock des notifications
    with patch('app.services.project_monitoring.ProjectMonitoringService._send_disabled_notification', new_callable=AsyncMock) as mock_notification:
        await ProjectMonitoringService.check_inactive_projects(db)
        
        # Vérifier que le projet a été désactivé
        await db.refresh(project)
        assert project.status == "inactive"
        assert project.deactivated_at is not None
        
        # Vérifier que la notification a été envoyée
        mock_notification.assert_called_once()


@pytest.mark.asyncio
async def test_check_permanently_disabled_projects(db: AsyncSession):
    """Test de désactivation permanente après 7 jours supplémentaires"""
    # Créer un projet déjà inactif depuis 8 jours
    eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="inactive",
        deactivated_at=eight_days_ago
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Exécuter la vérification avec mock des notifications
    with patch('app.services.project_monitoring.ProjectMonitoringService._send_permanently_disabled_notification', new_callable=AsyncMock) as mock_notification:
        await ProjectMonitoringService.check_permanently_disabled_projects(db)
        
        # Vérifier que le projet a été désactivé définitivement
        await db.refresh(project)
        assert project.status == "permanently_disabled"
        
        # Vérifier que la notification a été envoyée
        mock_notification.assert_called_once()


@pytest.mark.asyncio
async def test_reactivate_project_success(db: AsyncSession):
    """Test de réactivation réussie d'un projet inactif"""
    # Créer un projet inactif
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="inactive",
        deactivated_at=datetime.now(timezone.utc)
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Créer un domaine pour le projet
    domain = Domain(
        project_id=project.id,
        hostname="test.example.com",
        type="route",
        status="disabled"
    )
    db.add(domain)
    await db.commit()
    
    # Réactiver le projet
    success = await ProjectMonitoringService.reactivate_project(project, db)
    
    # Vérifier la réactivation
    assert success is True
    await db.refresh(project)
    assert project.status == "active"
    assert project.deactivated_at is None
    assert project.reactivation_count == 1
    
    # Vérifier que le domaine a été réactivé
    await db.refresh(domain)
    assert domain.status == "active"


@pytest.mark.asyncio
async def test_reactivate_project_permanently_disabled(db: AsyncSession):
    """Test de réactivation impossible d'un projet définitivement désactivé"""
    # Créer un projet définitivement désactivé
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="permanently_disabled",
        deactivated_at=datetime.now(timezone.utc)
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Tenter de réactiver le projet
    success = await ProjectMonitoringService.reactivate_project(project, db)
    
    # Vérifier que la réactivation a échoué
    assert success is False
    await db.refresh(project)
    assert project.status == "permanently_disabled"


@pytest.mark.asyncio
async def test_record_traffic(db: AsyncSession):
    """Test d'enregistrement du trafic"""
    # Créer un projet
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="active"
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Enregistrer le trafic
    await ProjectMonitoringService.record_traffic(project, db)
    
    # Vérifier que last_traffic_at a été mis à jour
    await db.refresh(project)
    assert project.last_traffic_at is not None
    assert (datetime.now(timezone.utc) - project.last_traffic_at).total_seconds() < 5


@pytest.mark.asyncio
async def test_get_project_by_domain(db: AsyncSession):
    """Test de récupération d'un projet par domaine"""
    # Créer un projet et un domaine
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="active"
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    domain = Domain(
        project_id=project.id,
        hostname="test.example.com",
        type="route",
        status="active"
    )
    db.add(domain)
    await db.commit()
    
    # Récupérer le projet par domaine
    found_project = await ProjectMonitoringService.get_project_by_domain(db, "test.example.com")
    
    # Vérifier que le projet a été trouvé
    assert found_project is not None
    assert found_project.id == project.id


@pytest.mark.asyncio
async def test_pay_as_you_go_projects_not_affected(db: AsyncSession):
    """Test que les projets du plan payant ne sont pas affectés"""
    # Créer le plan payant
    pay_plan = await PricingService.get_pay_as_you_go_plan(db)
    
    # Créer un utilisateur et une équipe
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
    
    # Assigner le plan payant à l'équipe
    subscription = TeamSubscription(
        team_id=team.id,
        plan_id=pay_plan.id,
        status="active"
    )
    db.add(subscription)
    await db.commit()
    
    # Créer un projet inactif depuis 6 jours
    six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id=team.id,
        status="active",
        last_traffic_at=six_days_ago
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Exécuter la vérification
    await ProjectMonitoringService.check_inactive_projects(db)
    
    # Vérifier que le projet n'a PAS été désactivé
    await db.refresh(project)
    assert project.status == "active"
    assert project.deactivated_at is None


@pytest.mark.asyncio
async def test_project_can_be_reactivated():
    """Test de la méthode can_be_reactivated"""
    # Projet actif
    active_project = Project(
        name="Active Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="active"
    )
    assert active_project.can_be_reactivated() is True
    
    # Projet inactif
    inactive_project = Project(
        name="Inactive Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="inactive"
    )
    assert inactive_project.can_be_reactivated() is True
    
    # Projet définitivement désactivé
    disabled_project = Project(
        name="Disabled Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id="test-team",
        status="permanently_disabled"
    )
    assert disabled_project.can_be_reactivated() is False


@pytest.mark.asyncio
async def test_send_disabled_notification(db: AsyncSession):
    """Test d'envoi de notification de désactivation"""
    # Créer un utilisateur et une équipe
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
    
    # Créer un projet
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id=team.id,
        status="inactive",
        deactivated_at=datetime.now(timezone.utc)
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Mock du service de notification
    with patch('app.services.project_monitoring.DeploymentNotificationService') as mock_service_class:
        mock_service = AsyncMock()
        mock_service_class.return_value.__aenter__.return_value = mock_service
        mock_service.send_project_disabled_notification.return_value = True
        
        # Appeler la méthode de notification
        await ProjectMonitoringService._send_disabled_notification(project, db)
        
        # Vérifier que le service a été appelé
        mock_service.send_project_disabled_notification.assert_called_once_with(project, user, team)


@pytest.mark.asyncio
async def test_send_permanently_disabled_notification(db: AsyncSession):
    """Test d'envoi de notification de désactivation permanente"""
    # Créer un utilisateur et une équipe
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
    
    # Créer un projet
    project = Project(
        name="Test Project",
        repo_id=12345,
        repo_full_name="test/repo",
        github_installation_id=1,
        team_id=team.id,
        status="permanently_disabled",
        deactivated_at=datetime.now(timezone.utc)
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # Mock du service de notification
    with patch('app.services.project_monitoring.DeploymentNotificationService') as mock_service_class:
        mock_service = AsyncMock()
        mock_service_class.return_value.__aenter__.return_value = mock_service
        mock_service.send_project_permanently_disabled_notification.return_value = True
        
        # Appeler la méthode de notification
        await ProjectMonitoringService._send_permanently_disabled_notification(project, db)
        
        # Vérifier que le service a été appelé
        mock_service.send_project_permanently_disabled_notification.assert_called_once_with(project, user, team)
