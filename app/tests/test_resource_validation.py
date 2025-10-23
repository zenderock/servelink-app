"""
Tests pour la validation des ressources selon les plans d'abonnement
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from services.pricing import ResourceValidationService
from models import Team, SubscriptionPlan, Project


class TestResourceValidationService:
    """Tests pour ResourceValidationService"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock de la base de données"""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def free_plan(self):
        """Plan gratuit pour les tests"""
        plan = SubscriptionPlan()
        plan.name = "free"
        plan.display_name = "Free"
        plan.max_cpu_cores = 0.5
        plan.max_memory_mb = 500
        return plan
    
    @pytest.fixture
    def pay_as_you_go_plan(self):
        """Plan Pay as You Go pour les tests"""
        plan = SubscriptionPlan()
        plan.name = "pay_as_you_go"
        plan.display_name = "Pay as You Go"
        plan.max_cpu_cores = 4.0
        plan.max_memory_mb = 6144
        return plan
    
    @pytest.fixture
    def team_with_free_plan(self, free_plan):
        """Équipe avec plan gratuit"""
        team = Team()
        team._current_plan = free_plan
        return team
    
    @pytest.fixture
    def team_with_pay_plan(self, pay_as_you_go_plan):
        """Équipe avec plan Pay as You Go"""
        team = Team()
        team._current_plan = pay_as_you_go_plan
        return team
    
    @pytest.mark.asyncio
    async def test_validate_resources_free_plan_within_limits(self, team_with_free_plan, mock_db):
        """Test validation plan gratuit dans les limites"""
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_free_plan, 0.3, 300, mock_db
        )
        assert valid is True
        assert msg == ""
    
    @pytest.mark.asyncio
    async def test_validate_resources_free_plan_cpu_exceeded(self, team_with_free_plan, mock_db):
        """Test validation plan gratuit avec CPU dépassé"""
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_free_plan, 0.8, 300, mock_db
        )
        assert valid is False
        assert "CPU limit: 0.5 cores on Free" in msg
    
    @pytest.mark.asyncio
    async def test_validate_resources_free_plan_memory_exceeded(self, team_with_free_plan, mock_db):
        """Test validation plan gratuit avec mémoire dépassée"""
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_free_plan, 0.3, 600, mock_db
        )
        assert valid is False
        assert "Memory limit: 500MB on Free" in msg
    
    @pytest.mark.asyncio
    async def test_validate_resources_pay_plan_within_limits(self, team_with_pay_plan, mock_db):
        """Test validation plan Pay as You Go dans les limites"""
        # Mock pour simuler mémoire disponible
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0  # Aucune mémoire utilisée
        mock_db.execute.return_value = mock_result
        
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_pay_plan, 2.0, 2048, mock_db
        )
        assert valid is True
        assert msg == ""
    
    @pytest.mark.asyncio
    async def test_validate_resources_pay_plan_insufficient_memory(self, team_with_pay_plan, mock_db):
        """Test validation plan Pay as You Go avec mémoire insuffisante"""
        # Mock pour simuler mémoire déjà utilisée (6GB)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 6144  # 6GB déjà utilisés
        mock_db.execute.return_value = mock_result
        
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_pay_plan, 2.0, 2048, mock_db
        )
        assert valid is False
        assert "Insufficient memory" in msg
        assert "0MB available" in msg
    
    @pytest.mark.asyncio
    async def test_validate_resources_no_plan(self, mock_db):
        """Test validation sans plan actif"""
        team = Team()
        team._current_plan = None
        
        valid, msg = await ResourceValidationService.validate_resources(
            team, 0.5, 1000, mock_db
        )
        assert valid is False
        assert msg == "No active plan found"
    
    @pytest.mark.asyncio
    async def test_get_available_memory_no_used_memory(self, team_with_pay_plan, mock_db):
        """Test calcul mémoire disponible sans projets existants"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = None  # Aucune mémoire utilisée
        mock_db.execute.return_value = mock_result
        
        available = await ResourceValidationService.get_available_memory(team_with_pay_plan, mock_db)
        assert available == 6144  # 8GB - 2GB système = 6GB
    
    @pytest.mark.asyncio
    async def test_get_available_memory_with_used_memory(self, team_with_pay_plan, mock_db):
        """Test calcul mémoire disponible avec projets existants"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 2048  # 2GB déjà utilisés
        mock_db.execute.return_value = mock_result
        
        available = await ResourceValidationService.get_available_memory(team_with_pay_plan, mock_db)
        assert available == 4096  # 6GB - 2GB = 4GB
    
    @pytest.mark.asyncio
    async def test_get_available_memory_fully_used(self, team_with_pay_plan, mock_db):
        """Test calcul mémoire disponible complètement utilisée"""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 8192  # 8GB utilisés (plus que disponible)
        mock_db.execute.return_value = mock_result
        
        available = await ResourceValidationService.get_available_memory(team_with_pay_plan, mock_db)
        assert available == 0  # max(0, 6144 - 8192) = 0
    
    @pytest.mark.asyncio
    async def test_validate_resources_none_values(self, team_with_free_plan, mock_db):
        """Test validation avec valeurs None"""
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_free_plan, None, None, mock_db
        )
        assert valid is True
        assert msg == ""
    
    @pytest.mark.asyncio
    async def test_validate_resources_cpu_only(self, team_with_free_plan, mock_db):
        """Test validation avec seulement CPU"""
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_free_plan, 0.3, None, mock_db
        )
        assert valid is True
        assert msg == ""
    
    @pytest.mark.asyncio
    async def test_validate_resources_memory_only(self, team_with_free_plan, mock_db):
        """Test validation avec seulement mémoire"""
        valid, msg = await ResourceValidationService.validate_resources(
            team_with_free_plan, None, 300, mock_db
        )
        assert valid is True
        assert msg == ""


class TestProjectResourcesForm:
    """Tests pour ProjectResourcesForm"""
    
    @pytest.fixture
    def form(self):
        """Formulaire de ressources pour les tests"""
        from forms.project import ProjectResourcesForm
        return ProjectResourcesForm()
    
    @pytest.fixture
    def mock_team(self, free_plan):
        """Équipe mock pour les tests"""
        team = Team()
        team._current_plan = free_plan
        return team
    
    @pytest.fixture
    def mock_db(self):
        """Base de données mock"""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.mark.asyncio
    async def test_validate_with_plan_valid_resources(self, form, mock_team, mock_db):
        """Test validation avec ressources valides"""
        form.cpus.data = 0.3
        form.memory.data = 300
        
        # Mock de ResourceValidationService
        with pytest.Mock() as mock_service:
            mock_service.validate_resources.return_value = (True, "")
            
            valid = await form.validate_with_plan(mock_team, mock_db)
            assert valid is True
            assert len(form.cpus.errors) == 0
            assert len(form.memory.errors) == 0
    
    @pytest.mark.asyncio
    async def test_validate_with_plan_invalid_cpu(self, form, mock_team, mock_db):
        """Test validation avec CPU invalide"""
        form.cpus.data = 0.8  # Dépassement de la limite
        form.memory.data = 300
        
        # Mock de ResourceValidationService
        with pytest.Mock() as mock_service:
            mock_service.validate_resources.return_value = (False, "CPU limit exceeded")
            
            valid = await form.validate_with_plan(mock_team, mock_db)
            assert valid is False
            assert len(form.cpus.errors) > 0
            assert "CPU limit exceeded" in form.cpus.errors[0]
    
    @pytest.mark.asyncio
    async def test_validate_with_plan_invalid_memory(self, form, mock_team, mock_db):
        """Test validation avec mémoire invalide"""
        form.cpus.data = 0.3
        form.memory.data = 600  # Dépassement de la limite
        
        # Mock de ResourceValidationService
        with pytest.Mock() as mock_service:
            mock_service.validate_resources.return_value = (False, "Memory limit exceeded")
            
            valid = await form.validate_with_plan(mock_team, mock_db)
            assert valid is False
            assert len(form.memory.errors) > 0
            assert "Memory limit exceeded" in form.memory.errors[0]
